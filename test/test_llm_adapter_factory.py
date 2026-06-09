from ouro.core.llm import LLMAdapter, create_llm_adapter
from ouro.core.llm.litellm_adapter import LiteLLMAdapter
from ouro.core.llm.openai_codex_adapter import OpenAICodexAdapter


def test_create_llm_adapter_routes_openai_codex_models() -> None:
    adapter = create_llm_adapter("openai-codex/gpt-5.5", timeout=123)

    assert isinstance(adapter, OpenAICodexAdapter)
    assert isinstance(adapter, LLMAdapter)
    assert adapter.model == "openai-codex/gpt-5.5"
    assert adapter.timeout == 123


def test_create_llm_adapter_routes_other_models_to_litellm() -> None:
    adapter = create_llm_adapter("openai/gpt-4o", api_key="test", timeout=123)

    assert isinstance(adapter, LiteLLMAdapter)
    assert isinstance(adapter, LLMAdapter)
    assert adapter.model == "openai/gpt-4o"
    assert adapter.api_key == "test"
    assert adapter.timeout == 123
