import pytest

import ouro.core.llm.oauth_model_catalog as catalog
from ouro.core.llm.oauth_model_catalog import (
    get_bundled_oauth_provider_model_ids,
    get_oauth_provider_model_ids,
)


def test_chatgpt_catalog_includes_latest_subscription_models():
    model_ids = get_oauth_provider_model_ids("chatgpt")

    assert "chatgpt/gpt-5.3-instant" in model_ids
    assert "chatgpt/gpt-5.4" in model_ids
    assert "chatgpt/gpt-5.4-pro" in model_ids
    assert "chatgpt/gpt-5.2" in model_ids
    assert "chatgpt/gpt-5.2-codex" in model_ids


def test_copilot_catalog_includes_expected_models():
    model_ids = get_bundled_oauth_provider_model_ids("copilot")

    assert "github_copilot/claude-opus-4.8" in model_ids
    assert "github_copilot/claude-sonnet-4.6" in model_ids
    assert "github_copilot/gpt-5.5" in model_ids
    assert "github_copilot/gemini-3.5-flash" in model_ids
    assert "github_copilot/mai-code-1-flash" in model_ids
    assert all(mid.startswith("github_copilot/") for mid in model_ids)


def test_catalog_rejects_unsupported_provider():
    with pytest.raises(ValueError, match="Unsupported provider"):
        get_oauth_provider_model_ids("unknown")


def test_catalog_uses_dynamic_models_when_available(monkeypatch):
    monkeypatch.setattr(catalog.Config, "OAUTH_MODEL_DYNAMIC_REFRESH", True)
    monkeypatch.setattr(
        catalog,
        "discover_oauth_provider_model_ids",
        lambda provider: (f"{provider}/latest",),
    )

    assert get_oauth_provider_model_ids("chatgpt") == ("chatgpt/latest",)


def test_catalog_can_disable_dynamic_refresh(monkeypatch):
    monkeypatch.setattr(catalog.Config, "OAUTH_MODEL_DYNAMIC_REFRESH", False)
    monkeypatch.setattr(
        catalog,
        "discover_oauth_provider_model_ids",
        lambda provider: (_ for _ in ()).throw(AssertionError("should not refresh")),
    )

    assert get_oauth_provider_model_ids("chatgpt") == get_bundled_oauth_provider_model_ids(
        "chatgpt"
    )


def test_catalog_dynamic_refresh_failure_raises(monkeypatch):
    monkeypatch.setattr(catalog.Config, "OAUTH_MODEL_DYNAMIC_REFRESH", True)
    monkeypatch.setattr(
        catalog,
        "discover_oauth_provider_model_ids",
        lambda provider: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        get_oauth_provider_model_ids("copilot")
