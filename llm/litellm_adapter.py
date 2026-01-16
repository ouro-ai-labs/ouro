"""LiteLLM adapter for unified LLM access across 100+ providers."""

import json
import logging
from typing import Any, Dict, List, Optional

import litellm

from utils import get_logger

from .base import LLMMessage, LLMResponse, ToolCall, ToolResult
from .retry import RetryConfig, with_retry

logger = get_logger(__name__)

# Suppress LiteLLM's verbose logging to console
# LiteLLM uses its own logger that prints to console by default
litellm_logger = logging.getLogger("LiteLLM")
litellm_logger.setLevel(logging.WARNING)  # Only show warnings and errors
litellm_logger.propagate = False  # Don't propagate to root logger


class LiteLLMLLM:
    """LiteLLM adapter supporting 100+ LLM providers."""

    def __init__(self, model: str, **kwargs):
        """Initialize LiteLLM adapter.

        Args:
            model: LiteLLM model identifier (e.g., "anthropic/claude-3-5-sonnet-20241022")
            **kwargs: Additional configuration:
                - api_key: API key (optional, uses env vars by default)
                - api_base: Custom base URL
                - retry_config: RetryConfig instance
                - drop_params: Drop unsupported params (default: True)
                - timeout: Request timeout in seconds
        """
        # Extract model and provider
        self.model = model
        self.provider = model.split("/")[0] if "/" in model else "unknown"

        # Extract configuration from kwargs
        self.api_key = kwargs.pop("api_key", None)
        self.api_base = kwargs.pop("api_base", None)
        self.drop_params = kwargs.pop("drop_params", True)
        self.timeout = kwargs.pop("timeout", 600)

        # Configure retry behavior
        self.retry_config = kwargs.pop(
            "retry_config", RetryConfig(max_retries=3, initial_delay=1.0, max_delay=60.0)
        )

        # Configure LiteLLM global settings
        litellm.drop_params = self.drop_params
        litellm.set_verbose = False  # Disable verbose output
        litellm.suppress_debug_info = True  # Suppress debug info

        # Also suppress httpx and openai loggers that LiteLLM uses
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)
        logging.getLogger("anthropic").setLevel(logging.WARNING)

        logger.info(f"Initialized LiteLLM adapter for provider: {self.provider}, model: {model}")

    @with_retry()
    def _make_api_call(self, **call_params):
        """Internal method to make API call with retry logic."""
        return litellm.completion(**call_params)

    def call(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LLMResponse:
        """Call LLM via LiteLLM with automatic retry.

        Args:
            messages: List of conversation messages
            tools: Optional list of tool schemas (Anthropic format)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters

        Returns:
            LLMResponse with unified format
        """
        # Convert LLMMessage to LiteLLM format (OpenAI-compatible)
        litellm_messages = self._convert_messages(messages)

        # Prepare API call parameters
        call_params = {
            "model": self.model,
            "messages": litellm_messages,
            "max_tokens": max_tokens,
            "timeout": self.timeout,
        }

        # Add API key if provided
        if self.api_key:
            call_params["api_key"] = self.api_key

        # Add custom base URL if provided
        if self.api_base:
            call_params["api_base"] = self.api_base

        # Convert tools to OpenAI format if provided
        if tools:
            call_params["tools"] = self._convert_tools(tools)

        # Add any additional parameters
        call_params.update(kwargs)

        # Make API call with retry logic
        logger.debug(
            f"Calling LiteLLM with model: {self.model}, messages: {len(litellm_messages)}, tools: {len(tools) if tools else 0}"
        )
        response = self._make_api_call(**call_params)

        # Log token usage
        if hasattr(response, "usage") and response.usage:
            usage = response.usage
            logger.debug(
                f"Token Usage: Input={usage.get('prompt_tokens', 0)}, "
                f"Output={usage.get('completion_tokens', 0)}, "
                f"Total={usage.get('total_tokens', 0)}"
            )

        # Convert to unified format
        return self._convert_response(response)

    def _convert_messages(self, messages: List[LLMMessage]) -> List[Dict]:
        """Convert LLMMessage to LiteLLM format (OpenAI-compatible)."""
        litellm_messages = []

        for msg in messages:
            # Handle system messages
            if msg.role == "system":
                litellm_messages.append({"role": "system", "content": msg.content})

            # Handle user messages
            elif msg.role == "user":
                if isinstance(msg.content, str):
                    litellm_messages.append({"role": "user", "content": msg.content})
                elif isinstance(msg.content, list):
                    # Handle tool results (Anthropic format)
                    content = self._convert_tool_results_to_text(msg.content)
                    litellm_messages.append({"role": "user", "content": content})

            # Handle assistant messages
            elif msg.role == "assistant":
                if isinstance(msg.content, str):
                    litellm_messages.append({"role": "assistant", "content": msg.content})
                else:
                    # Handle complex content (tool calls, etc.)
                    content = self._extract_assistant_content(msg.content)
                    if content:
                        litellm_messages.append({"role": "assistant", "content": content})

        return litellm_messages

    def _convert_tool_results_to_text(self, content: List) -> str:
        """Convert Anthropic tool_result format to text for LiteLLM."""
        # LiteLLM handles tool results as text in user messages
        results = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_id = block.get("tool_use_id", "unknown")
                tool_content = block.get("content", "")
                results.append(f"Tool result (ID: {tool_id}):\n{tool_content}")
        return "\n\n".join(results) if results else str(content)

    def _extract_assistant_content(self, content: Any) -> str:
        """Extract text from assistant content."""
        if isinstance(content, str):
            return content

        # Handle Message objects (from previous LLM responses)
        # This prevents nested Message objects from being stringified
        if hasattr(content, "content"):
            return self._extract_assistant_content(content.content)

        # Handle Anthropic content blocks
        if isinstance(content, list):
            texts = []
            for block in content:
                if hasattr(block, "text"):
                    texts.append(block.text)
                elif isinstance(block, dict):
                    if "text" in block:
                        texts.append(block["text"])
                    elif block.get("type") == "text":
                        texts.append(block.get("text", ""))
            return "\n".join(texts) if texts else ""

        return str(content)

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict]:
        """Convert Anthropic tool format to OpenAI format."""
        openai_tools = []
        for tool in tools:
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                }
            )
        return openai_tools

    def _convert_response(self, response) -> LLMResponse:
        """Convert LiteLLM response to LLMResponse."""
        # Extract message
        message = response.choices[0].message

        # Determine stop reason
        finish_reason = response.choices[0].finish_reason
        if finish_reason == "tool_calls":
            stop_reason = "tool_use"
        elif finish_reason == "stop":
            stop_reason = "end_turn"
        elif finish_reason == "length":
            stop_reason = "max_tokens"
        else:
            stop_reason = finish_reason or "end_turn"

        # Extract token usage
        usage_dict = None
        if hasattr(response, "usage") and response.usage:
            usage_dict = {
                "input_tokens": response.usage.get("prompt_tokens", 0),
                "output_tokens": response.usage.get("completion_tokens", 0),
            }

        return LLMResponse(message=message, stop_reason=stop_reason, usage=usage_dict)

    def extract_text(self, response: LLMResponse) -> str:
        """Extract text from LiteLLM response."""
        message = response.message
        return message.content if hasattr(message, "content") and message.content else ""

    def extract_tool_calls(self, response: LLMResponse) -> List[ToolCall]:
        """Extract tool calls from LiteLLM response."""
        tool_calls = []
        message = response.message

        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments)
                    )
                )
        else:
            logger.debug(f"No tool calls found in the response. {message}")

        return tool_calls

    def format_tool_results(self, results: List[ToolResult]) -> LLMMessage:
        """Format tool results for LiteLLM."""
        # LiteLLM expects tool results as user messages
        # Format as Anthropic-style for compatibility with existing code
        content = []
        for result in results:
            content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": result.tool_call_id,
                    "content": result.content,
                }
            )

        return LLMMessage(role="user", content=content)

    @property
    def supports_tools(self) -> bool:
        """Most LiteLLM providers support tool calling."""
        # Most providers support tools, return True by default
        # LiteLLM will handle unsupported cases gracefully
        return True

    @property
    def provider_name(self) -> str:
        """Name of the LLM provider."""
        return self.provider.upper()
