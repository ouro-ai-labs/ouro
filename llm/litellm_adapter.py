"""LiteLLM adapter for unified LLM access across 100+ providers."""

import json
import logging
from typing import Any, Dict, List, Optional

import litellm

from utils import get_logger

from .base import LLMMessage, LLMResponse, ToolCall, ToolResult
from .retry import with_retry

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
        """Convert tool results to text for LiteLLM."""
        # LiteLLM handles tool results as text in user messages
        results = []
        for block in content:
            if isinstance(block, dict):
                # New simple format: {"tool_call_id": "...", "content": "..."}
                if "tool_call_id" in block:
                    tool_id = block.get("tool_call_id", "unknown")
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

    def _clean_message(self, message) -> None:
        """Clean up unnecessary fields from message to reduce memory usage.

        Removes:
        - provider_specific_fields (contains thought_signature)
        - __thought__ suffix from tool call IDs

        These fields are added by Anthropic's extended thinking feature and
        can be very large (2-3KB each), serving no purpose for agent operation.
        """
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                # Remove provider_specific_fields if present
                if hasattr(tc, "provider_specific_fields"):
                    tc.provider_specific_fields = None

                # Clean __thought__ suffix from tool call ID
                # e.g., "call_abc123__thought__xxx..." -> "call_abc123"
                if hasattr(tc, "id") and tc.id and "__thought__" in tc.id:
                    tc.id = tc.id.split("__thought__")[0]

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
        raw_message = response.choices[0].message

        # Clean up provider_specific_fields (removes thought_signature, etc.)
        # These fields are large and not useful for agent operation
        self._clean_message(raw_message)

        # Convert to LLMMessage
        message = self._convert_to_llm_message(raw_message)

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

        return LLMResponse(
            message=message, stop_reason=stop_reason, usage=usage_dict, _raw_message=raw_message
        )

    def _convert_to_llm_message(self, raw_message) -> LLMMessage:
        """Convert LiteLLM message object to LLMMessage.

        Args:
            raw_message: LiteLLM ChatCompletionMessage object

        Returns:
            LLMMessage with properly extracted content and tool_calls
        """
        # Extract content
        content = raw_message.content if hasattr(raw_message, "content") else ""

        # Extract tool_calls if present
        tool_calls = None
        if hasattr(raw_message, "tool_calls") and raw_message.tool_calls:
            tool_calls = []
            for tc in raw_message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                    )
                )

        return LLMMessage(role="assistant", content=content or "", tool_calls=tool_calls)

    def extract_text(self, response: LLMResponse) -> str:
        """Extract text from LLMResponse.

        Args:
            response: LLMResponse object

        Returns:
            Text content from the message
        """
        message = response.message
        if isinstance(message, LLMMessage):
            content = message.content
            return content if isinstance(content, str) else ""
        return ""

    def extract_tool_calls(self, response: LLMResponse) -> List[ToolCall]:
        """Extract tool calls from LLMResponse.

        Args:
            response: LLMResponse object

        Returns:
            List of ToolCall objects
        """
        message = response.message
        if isinstance(message, LLMMessage) and message.tool_calls:
            return message.tool_calls
        return []

    def extract_thinking(self, response: LLMResponse) -> Optional[str]:
        """Extract thinking/reasoning content from LLM response.

        Anthropic's extended thinking feature returns thinking content in various ways:
        - message.thinking_blocks (list of thinking blocks)
        - message.reasoning_content (OpenAI o1 style)
        - content blocks with type="thinking"

        Args:
            response: LLM response

        Returns:
            Thinking content string or None if not present
        """
        # Use raw_message for provider-specific features
        raw_message = response._raw_message
        if not raw_message:
            return None

        thinking_parts = []

        # Check for thinking_blocks (Anthropic extended thinking via LiteLLM)
        if hasattr(raw_message, "thinking_blocks") and raw_message.thinking_blocks:
            for block in raw_message.thinking_blocks:
                if hasattr(block, "thinking"):
                    thinking_parts.append(block.thinking)
                elif isinstance(block, dict) and "thinking" in block:
                    thinking_parts.append(block["thinking"])
                elif isinstance(block, str):
                    thinking_parts.append(block)

        # Check for reasoning_content (OpenAI o1 style)
        if hasattr(raw_message, "reasoning_content") and raw_message.reasoning_content:
            thinking_parts.append(raw_message.reasoning_content)

        # Check content blocks for thinking type
        if hasattr(raw_message, "content") and isinstance(raw_message.content, list):
            for block in raw_message.content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    thinking_parts.append(block.get("thinking", ""))
                elif hasattr(block, "type") and block.type == "thinking":
                    thinking_parts.append(getattr(block, "thinking", ""))

        return "\n\n".join(thinking_parts) if thinking_parts else None

    def format_tool_results(self, results: List[ToolResult]) -> LLMMessage:
        """Format tool results for LiteLLM.

        Uses a simple format compatible with OpenAI/LiteLLM:
        - List of dicts with tool_call_id and content
        """
        content = []
        for result in results:
            content.append(
                {
                    "tool_call_id": result.tool_call_id,
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
