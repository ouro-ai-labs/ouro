"""LiteLLM adapter for unified LLM access across 100+ providers."""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

import litellm

from utils import get_logger

from .content_utils import extract_text, extract_tool_calls_from_content
from .message_types import (
    LLMMessage,
    LLMResponse,
    StopReason,
    ToolCall,
    ToolCallBlock,
    ToolResult,
)
from .retry import with_retry

logger = get_logger(__name__)

# Suppress LiteLLM's verbose logging to console
# LiteLLM uses its own logger that prints to console by default
litellm_logger = logging.getLogger("LiteLLM")
litellm_logger.setLevel(logging.WARNING)  # Only show warnings and errors
litellm_logger.propagate = False  # Don't propagate to root logger


class LiteLLMAdapter:
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
    async def _make_api_call_async(self, **call_params):
        """Internal async API call with retry logic."""
        acompletion = getattr(litellm, "acompletion", None)
        if acompletion is None:
            raise RuntimeError("LiteLLM async completion is unavailable.")
        return await acompletion(**call_params)

    def _build_call_params(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]],
        max_tokens: int,
        **kwargs,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Prepare LiteLLM call parameters and converted messages."""
        litellm_messages = self._convert_messages(messages)

        call_params: Dict[str, Any] = {
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

        return litellm_messages, call_params

    async def call_async(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LLMResponse:
        """Async LLM call via LiteLLM with automatic retry."""
        litellm_messages, call_params = self._build_call_params(
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            **kwargs,
        )

        logger.debug(
            f"Calling LiteLLM async with model: {self.model}, messages: {len(litellm_messages)}, tools: {len(tools) if tools else 0}"
        )
        response = await self._make_api_call_async(**call_params)

        if hasattr(response, "usage") and response.usage:
            usage = response.usage
            logger.debug(
                f"Token Usage: Input={usage.get('prompt_tokens', 0)}, "
                f"Output={usage.get('completion_tokens', 0)}, "
                f"Total={usage.get('total_tokens', 0)}"
            )

        return self._convert_response(response)

    def _convert_messages(self, messages: List[LLMMessage]) -> List[Dict]:
        """Convert LLMMessage to LiteLLM format (OpenAI-compatible).

        Handles both new format (tool_calls field, tool role) and legacy format
        (tool_result blocks in user content).
        """
        litellm_messages = []

        for msg in messages:
            # Handle system messages
            if msg.role == "system":
                content = msg.content if isinstance(msg.content, str) else extract_text(msg.content)
                litellm_messages.append({"role": "system", "content": content})

            # Handle tool messages (new OpenAI format)
            elif msg.role == "tool":
                litellm_messages.append(
                    {
                        "role": "tool",
                        "content": msg.content or "",
                        "tool_call_id": msg.tool_call_id or "",
                    }
                )

            # Handle user messages
            elif msg.role == "user":
                if isinstance(msg.content, str):
                    litellm_messages.append({"role": "user", "content": msg.content})
                elif isinstance(msg.content, list):
                    # Legacy: Handle tool results (Anthropic format)
                    # Convert to tool messages for OpenAI compatibility
                    tool_messages = self._convert_anthropic_tool_results(msg.content)
                    if tool_messages:
                        litellm_messages.extend(tool_messages)
                    else:
                        # Not tool results, extract text
                        content = extract_text(msg.content)
                        litellm_messages.append({"role": "user", "content": content})
                else:
                    content = extract_text(msg.content)
                    litellm_messages.append({"role": "user", "content": content})

            # Handle assistant messages
            elif msg.role == "assistant":
                assistant_msg: Dict[str, Any] = {"role": "assistant"}

                # New format: tool_calls field
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    assistant_msg["tool_calls"] = msg.tool_calls
                    # Content can be None or text
                    if msg.content:
                        assistant_msg["content"] = msg.content
                    else:
                        assistant_msg["content"] = None
                # Simple string content
                elif isinstance(msg.content, str):
                    assistant_msg["content"] = msg.content
                # Legacy: complex content (may contain tool calls)
                else:
                    # Extract tool calls from legacy format
                    tool_calls = extract_tool_calls_from_content(msg.content)
                    if tool_calls:
                        assistant_msg["tool_calls"] = tool_calls
                        # Also extract any text content
                        text = extract_text(msg.content)
                        assistant_msg["content"] = text if text else None
                    else:
                        content = extract_text(msg.content)
                        assistant_msg["content"] = content if content else ""

                litellm_messages.append(assistant_msg)

        return litellm_messages

    def _convert_anthropic_tool_results(self, content: List) -> List[Dict]:
        """Convert Anthropic tool_result format to OpenAI tool messages.

        Args:
            content: List of content blocks potentially containing tool_result

        Returns:
            List of tool messages in OpenAI format, or empty list if not tool results
        """
        return [
            {
                "role": "tool",
                "content": block.get("content", ""),
                "tool_call_id": block.get("tool_use_id", ""),
            }
            for block in content
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]

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
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }
            for tool in tools
        ]

    def _convert_response(self, response) -> LLMResponse:
        """Convert LiteLLM response to LLMResponse with normalized content.

        Key change: Instead of storing the raw message object, we extract
        and normalize all content to ensure JSON serializability.
        """
        # Extract message from response
        message = response.choices[0].message

        # Clean up provider_specific_fields (removes thought_signature, etc.)
        self._clean_message(message)

        # Determine stop reason (normalize to OpenAI format)
        finish_reason = response.choices[0].finish_reason
        stop_reason = StopReason.normalize(finish_reason or "stop")

        # Extract text content
        content = None
        if hasattr(message, "content") and message.content:
            content = (
                message.content
                if isinstance(message.content, str)
                else extract_text(message.content)
            )

        # Extract and normalize tool calls
        tool_calls = None
        if hasattr(message, "tool_calls") and message.tool_calls:
            tool_calls = self._normalize_tool_calls(message.tool_calls)

        # Extract token usage
        usage_dict = None
        if hasattr(response, "usage") and response.usage:
            usage_dict = {
                "input_tokens": response.usage.get("prompt_tokens", 0),
                "output_tokens": response.usage.get("completion_tokens", 0),
            }

        # Extract thinking content
        thinking = self._extract_thinking_from_message(message)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage_dict,
            thinking=thinking,
        )

    def _normalize_tool_calls(self, tool_calls: List) -> List[ToolCallBlock]:
        """Normalize tool calls to OpenAI format.

        Args:
            tool_calls: List of tool calls from LiteLLM response

        Returns:
            List of ToolCallBlock in standard format
        """
        normalized: List[ToolCallBlock] = []
        for tc in tool_calls:
            # Get arguments as string
            arguments = tc.function.arguments
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments)

            tool_call: ToolCallBlock = {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": arguments,
                },
            }
            normalized.append(tool_call)
        return normalized

    def _extract_thinking_from_message(self, message) -> Optional[str]:
        """Extract thinking/reasoning content from message.

        Args:
            message: Message object from LiteLLM response

        Returns:
            Thinking content string or None
        """
        thinking_parts = []

        # Check for thinking_blocks (Anthropic extended thinking via LiteLLM)
        if hasattr(message, "thinking_blocks") and message.thinking_blocks:
            for block in message.thinking_blocks:
                if hasattr(block, "thinking"):
                    thinking_parts.append(block.thinking)
                elif isinstance(block, dict) and "thinking" in block:
                    thinking_parts.append(block["thinking"])
                elif isinstance(block, str):
                    thinking_parts.append(block)

        # Check for reasoning_content (OpenAI o1 style)
        if hasattr(message, "reasoning_content") and message.reasoning_content:
            thinking_parts.append(message.reasoning_content)

        # Check content blocks for thinking type
        if hasattr(message, "content") and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    thinking_parts.append(block.get("thinking", ""))
                elif hasattr(block, "type") and block.type == "thinking":
                    thinking_parts.append(getattr(block, "thinking", ""))

        return "\n\n".join(thinking_parts) if thinking_parts else None

    def extract_text(self, response: LLMResponse) -> str:
        """Extract text from LLMResponse.

        With the new format, content is already extracted and normalized.
        """
        return response.content or ""

    def extract_tool_calls(self, response: LLMResponse) -> List[ToolCall]:
        """Extract tool calls from LLMResponse.

        With the new format, tool_calls are already normalized to OpenAI format.
        This method parses the JSON arguments into dicts.
        """
        if not response.tool_calls:
            return []

        tool_calls = []
        for tc in response.tool_calls:
            try:
                arguments = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                arguments = {}

            tool_calls.append(
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=arguments,
                )
            )

        return tool_calls

    def extract_thinking(self, response: LLMResponse) -> Optional[str]:
        """Extract thinking/reasoning content from LLMResponse.

        With the new format, thinking is already extracted during response conversion.
        """
        return response.thinking

    def format_tool_results(self, results: List[ToolResult]) -> Union[LLMMessage, List[LLMMessage]]:
        """Format tool results for LiteLLM in OpenAI format.

        Returns a list of tool messages, one per result. This is the standard
        OpenAI format that LiteLLM expects for tool responses.

        Args:
            results: List of ToolResult objects

        Returns:
            List of LLMMessages with role="tool"
        """
        return [
            LLMMessage(
                role="tool",
                content=result.content,
                tool_call_id=result.tool_call_id,
                name=result.name if hasattr(result, "name") else None,
            )
            for result in results
        ]

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
