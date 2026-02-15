import pytest

from llm.oauth_model_catalog import get_oauth_provider_model_ids


def test_chatgpt_catalog_includes_gpt53():
    model_ids = get_oauth_provider_model_ids("chatgpt")

    assert "chatgpt/gpt-5.3-codex" in model_ids
    assert "chatgpt/gpt-5.3-codex-spark" in model_ids


def test_catalog_rejects_unsupported_provider():
    with pytest.raises(ValueError, match="Unsupported provider"):
        get_oauth_provider_model_ids("unknown")
