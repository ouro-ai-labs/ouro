"""OpenAI GPT LLM implementation."""
from typing import List, Dict, Any, Optional
import json

from .base import BaseLLM, LLMMessage, LLMResponse, ToolCall, ToolResult


class OpenAILLM(BaseLLM):
    """OpenAI GPT LLM provider."""

    def __init__(self, api_key: str, model: str = "gpt-4o", **kwargs):
        """Initialize OpenAI LLM.

        Args:
            api_key: OpenAI API key
            model: GPT model identifier (e.g., gpt-4o, gpt-4-turbo, gpt-3.5-turbo)
            **kwargs: Additional configuration
        """
        super().__init__(api_key, model, **kwargs)

        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError(
                "OpenAI package not installed. Install with: pip install openai"
            )

    def call(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
        **kwargs
    ) -> LLMResponse:
        """Call OpenAI API.

        Args:
            messages: List of conversation messages
            tools: Optional list of tool schemas
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters (temperature, etc.)

        Returns:
            LLMResponse with unified format
        """
        # Convert LLMMessage to OpenAI format
        openai_messages = []

        for msg in messages:
            # Handle different content types
            if isinstance(msg.content, str):
                openai_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })
            elif isinstance(msg.content, list):
                # Handle tool results
                content_parts = []
                for item in msg.content:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        content_parts.append({
                            "type": "text",
                            "text": item["content"]
                        })
                    else:
                        content_parts.append(item)

                openai_messages.append({
                    "role": msg.role,
                    "content": content_parts if content_parts else msg.content
                })
            else:
                openai_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })

        # Prepare API call parameters
        call_params = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": openai_messages,
        }

        # Convert tools to OpenAI format if provided
        if tools:
            openai_tools = []
            for tool in tools:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"]
                    }
                })
            call_params["tools"] = openai_tools

        # Add any additional parameters
        call_params.update(kwargs)

        # Make API call
        response = self.client.chat.completions.create(**call_params)

        # Determine stop reason
        finish_reason = response.choices[0].finish_reason
        if finish_reason == "tool_calls":
            stop_reason = "tool_use"
        elif finish_reason == "stop":
            stop_reason = "end_turn"
        elif finish_reason == "length":
            stop_reason = "max_tokens"
        else:
            stop_reason = finish_reason

        # Convert to unified format
        return LLMResponse(
            content=response.choices[0].message,
            stop_reason=stop_reason,
            raw_response=response
        )

    def extract_text(self, response: LLMResponse) -> str:
        """Extract text from OpenAI response.

        Args:
            response: LLMResponse object

        Returns:
            Extracted text
        """
        message = response.content
        return message.content if message.content else ""

    def extract_tool_calls(self, response: LLMResponse) -> List[ToolCall]:
        """Extract tool calls from OpenAI response.

        Args:
            response: LLMResponse object

        Returns:
            List of ToolCall objects
        """
        tool_calls = []
        message = response.content

        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments)
                ))

        return tool_calls

    def format_tool_results(self, results: List[ToolResult]) -> LLMMessage:
        """Format tool results for OpenAI.

        Args:
            results: List of tool results

        Returns:
            LLMMessage with formatted results
        """
        # OpenAI expects tool results as separate messages
        # For simplicity, we'll combine them into a single user message
        combined_content = "\n\n".join([
            f"Tool {result.tool_call_id} result: {result.content}"
            for result in results
        ])

        return LLMMessage(role="user", content=combined_content)

    @property
    def supports_tools(self) -> bool:
        """OpenAI supports tool calling."""
        return True
