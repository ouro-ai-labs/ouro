"""Anthropic Claude LLM implementation."""
from typing import List, Dict, Any, Optional
import anthropic

from .base import BaseLLM, LLMMessage, LLMResponse, ToolCall, ToolResult
from .retry import with_retry, RetryConfig


class AnthropicLLM(BaseLLM):
    """Anthropic Claude LLM provider."""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022", **kwargs):
        """Initialize Anthropic LLM.

        Args:
            api_key: Anthropic API key
            model: Claude model identifier
            **kwargs: Additional configuration (including retry_config)
        """
        super().__init__(api_key, model, **kwargs)
        self.client = anthropic.Anthropic(api_key=api_key, base_url="https://api.xiaomimimo.com/anthropic")

        # Configure retry behavior
        self.retry_config = kwargs.get('retry_config', RetryConfig(
            max_retries=5,
            initial_delay=1.0,
            max_delay=60.0
        ))

    @with_retry()
    def _make_api_call(self, **call_params):
        """Internal method to make API call with retry logic."""
        return self.client.messages.create(**call_params)

    def call(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
        **kwargs
    ) -> LLMResponse:
        """Call Claude API with automatic retry on rate limits.

        Args:
            messages: List of conversation messages
            tools: Optional list of tool schemas
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters (system, temperature, etc.)

        Returns:
            LLMResponse with unified format
        """
        # Convert LLMMessage to Anthropic format
        anthropic_messages = []
        system_message = None

        for msg in messages:
            if msg.role == "system":
                system_message = msg.content
            else:
                anthropic_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })

        # Prepare API call parameters
        call_params = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": anthropic_messages,
        }

        # Add system message if present
        if system_message:
            call_params["system"] = system_message
        elif kwargs.get("system"):
            call_params["system"] = kwargs.pop("system")

        # Add tools if provided
        if tools:
            call_params["tools"] = tools

        # Add any additional parameters
        call_params.update(kwargs)

        # Make API call with retry logic
        response = self._make_api_call(**call_params)

        # Print token usage
        if hasattr(response, 'usage'):
            usage = response.usage
            print(f"\n📊 Token Usage: Input={usage.input_tokens}, Output={usage.output_tokens}, Total={usage.input_tokens + usage.output_tokens}")

        # Convert to unified format
        return LLMResponse(
            content=response.content,
            stop_reason=response.stop_reason,
            raw_response=response
        )

    def extract_text(self, response: LLMResponse) -> str:
        """Extract text from Claude response.

        Args:
            response: LLMResponse object

        Returns:
            Extracted text
        """
        texts = []
        for block in response.content:
            if hasattr(block, "text"):
                texts.append(block.text)
        return "\n".join(texts) if texts else ""

    def extract_tool_calls(self, response: LLMResponse) -> List[ToolCall]:
        """Extract tool calls from Claude response.

        Args:
            response: LLMResponse object

        Returns:
            List of ToolCall objects
        """
        tool_calls = []
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input
                ))
        return tool_calls

    def format_tool_results(self, results: List[ToolResult]) -> LLMMessage:
        """Format tool results for Claude.

        Args:
            results: List of tool results

        Returns:
            LLMMessage with formatted results
        """
        content = []
        for result in results:
            content.append({
                "type": "tool_result",
                "tool_use_id": result.tool_call_id,
                "content": result.content
            })

        return LLMMessage(role="user", content=content)

    @property
    def supports_tools(self) -> bool:
        """Claude supports tool calling."""
        return True
