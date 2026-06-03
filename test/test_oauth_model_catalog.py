import pytest

from ouro.core.llm.oauth_model_catalog import get_oauth_provider_model_ids


def test_chatgpt_catalog_includes_gpt52():
    model_ids = get_oauth_provider_model_ids("chatgpt")

    assert "chatgpt/gpt-5.2" in model_ids
    assert "chatgpt/gpt-5.2-codex" in model_ids


def test_copilot_catalog_includes_expected_models():
    model_ids = get_oauth_provider_model_ids("copilot")

    assert "github_copilot/claude-opus-4.8" in model_ids
    assert "github_copilot/claude-sonnet-4.6" in model_ids
    assert "github_copilot/gpt-5.5" in model_ids
    assert "github_copilot/gemini-3.5-flash" in model_ids
    assert "github_copilot/mai-code-1-flash" in model_ids
    assert all(mid.startswith("github_copilot/") for mid in model_ids)


def test_catalog_rejects_unsupported_provider():
    with pytest.raises(ValueError, match="Unsupported provider"):
        get_oauth_provider_model_ids("unknown")
