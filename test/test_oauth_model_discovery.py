import sys
from types import SimpleNamespace

import ouro.core.llm.oauth_model_discovery as discovery


def test_copilot_markdown_extracts_model_ids():
    markdown = """
| Model name | Provider | Release status |
| ---------- | -------- | -------------- |
| GPT-5 mini | OpenAI | GA |
| GPT-5.3-Codex | OpenAI | GA |
| Claude Opus 4.6 (fast mode) (preview) | Anthropic | Preview |
| MAI-Code-1-Flash[^mai-code-1-flash] | Microsoft | GA |
"""

    names = discovery._extract_copilot_model_names(markdown)
    model_ids = [discovery._copilot_model_name_to_id(name) for name in names]

    assert model_ids == [
        "github_copilot/gpt-5-mini",
        "github_copilot/gpt-5.3-codex",
        "github_copilot/claude-opus-4.6-fast",
        "github_copilot/mai-code-1-flash",
    ]


def test_chatgpt_litellm_filter_includes_official_additions(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(
            chatgpt_models={
                "chatgpt/gpt-5.4",
                "chatgpt/gpt-5.3-instant",
                "chatgpt/gpt-5.4-pro",
            }
        ),
    )

    model_ids = discovery._merge_model_ids(
        ["gpt-5.4"],
        discovery.OFFICIAL_CHATGPT_SUBSCRIPTION_MODEL_IDS,
    )

    assert discovery._filter_chatgpt_model_ids_for_litellm(model_ids) == [
        "gpt-5.4",
        "gpt-5.3-instant",
        "gpt-5.4-pro",
    ]


def test_timeout_seconds_uses_config(monkeypatch):
    monkeypatch.setattr(discovery.Config, "OAUTH_MODEL_REFRESH_TIMEOUT_SECONDS", 2.5)

    assert discovery._get_timeout_seconds() == 2.5
