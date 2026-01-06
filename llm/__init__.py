"""LLM abstraction layer for multiple providers."""
from .base import BaseLLM, LLMMessage, LLMResponse, ToolCall, ToolResult
from .anthropic_llm import AnthropicLLM
from .openai_llm import OpenAILLM
from .gemini_llm import GeminiLLM


def create_llm(provider: str, api_key: str, model: str, **kwargs) -> BaseLLM:
    """Factory function to create LLM instances.

    Args:
        provider: LLM provider name ("anthropic", "openai", "gemini")
        api_key: API key for the provider
        model: Model identifier
        **kwargs: Additional provider-specific configuration

    Returns:
        BaseLLM instance

    Raises:
        ValueError: If provider is unknown
    """
    provider = provider.lower()

    if provider == "anthropic":
        return AnthropicLLM(api_key=api_key, model=model, **kwargs)
    elif provider == "openai":
        return OpenAILLM(api_key=api_key, model=model, **kwargs)
    elif provider == "gemini":
        return GeminiLLM(api_key=api_key, model=model, **kwargs)
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            f"Supported providers: anthropic, openai, gemini"
        )


__all__ = [
    "BaseLLM",
    "LLMMessage",
    "LLMResponse",
    "ToolCall",
    "ToolResult",
    "AnthropicLLM",
    "OpenAILLM",
    "GeminiLLM",
    "create_llm",
]
