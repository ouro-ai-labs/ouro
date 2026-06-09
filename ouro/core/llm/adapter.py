"""LLM adapter protocol and provider router."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .message_types import LLMMessage, LLMResponse, ToolCall, ToolResult


@runtime_checkable
class LLMAdapter(Protocol):
    """Runtime interface shared by concrete LLM provider adapters."""

    model: str

    async def call_async(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse: ...

    def extract_text(self, response: LLMResponse) -> str: ...

    def extract_tool_calls(self, response: LLMResponse) -> list[ToolCall]: ...

    def extract_thinking(self, response: LLMResponse) -> str | None: ...

    def format_tool_results(self, results: list[ToolResult]) -> LLMMessage | list[LLMMessage]: ...

    @property
    def supports_tools(self) -> bool: ...

    @property
    def provider_name(self) -> str: ...


def create_llm_adapter(model: str, **kwargs: Any) -> LLMAdapter:
    """Create the concrete adapter for a model ID."""
    provider = model.split("/", 1)[0] if "/" in model else "unknown"
    if provider == "openai-codex":
        from .openai_codex_adapter import OpenAICodexAdapter

        return OpenAICodexAdapter(model, **kwargs)

    from .litellm_adapter import LiteLLMAdapter

    return LiteLLMAdapter(model, **kwargs)
