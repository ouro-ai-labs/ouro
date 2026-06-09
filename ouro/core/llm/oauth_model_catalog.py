"""OAuth model catalog used to seed `~/.ouro/models.yaml` after login.

This file is intentionally deterministic and runtime-offline.

To refresh from pi-ai's latest published model registry, run:

    python scripts/update_oauth_model_catalog.py
"""

from __future__ import annotations

from ouro.config import Config
from ouro.core.llm.oauth_model_discovery import discover_oauth_provider_model_ids

PI_AI_VERSION = "0.73.1"
PI_AI_PROVIDER_ID = "openai-codex"

# ChatGPT entries are synced from pi-ai openai-codex provider model IDs.
# Other OAuth provider entries are preserved from the existing catalog.
OAUTH_PROVIDER_MODEL_IDS: dict[str, tuple[str, ...]] = {
    "chatgpt": (
        "openai-codex/gpt-5.5",
        "openai-codex/gpt-5.5-pro",
        "openai-codex/gpt-5.4",
        "openai-codex/gpt-5.4-pro",
        "openai-codex/gpt-5.3-instant",
        "openai-codex/gpt-5.3-codex",
        "openai-codex/gpt-5.3-codex-spark",
        "openai-codex/gpt-5.2",
        "openai-codex/gpt-5.2-codex",
        "openai-codex/gpt-5.1-codex-max",
        "openai-codex/gpt-5.1-codex-mini",
    ),
    "copilot": (
        "github_copilot/claude-opus-4.8",
        "github_copilot/claude-opus-4.7",
        "github_copilot/claude-opus-4.6",
        "github_copilot/claude-opus-4.5",
        "github_copilot/claude-sonnet-4.6",
        "github_copilot/claude-sonnet-4.5",
        "github_copilot/claude-haiku-4.5",
        "github_copilot/gpt-5.5",
        "github_copilot/gpt-5.4",
        "github_copilot/gpt-5.4-mini",
        "github_copilot/gpt-5.3-codex",
        "github_copilot/gemini-2.5-pro",
        "github_copilot/gemini-3.1-pro",
        "github_copilot/gemini-3.5-flash",
        "github_copilot/mai-code-1-flash",
    ),
}


def _dynamic_refresh_enabled() -> bool:
    return bool(Config.OAUTH_MODEL_DYNAMIC_REFRESH)


def get_bundled_oauth_provider_model_ids(provider: str) -> tuple[str, ...]:
    try:
        return OAUTH_PROVIDER_MODEL_IDS[provider]
    except KeyError as e:
        raise ValueError(f"Unsupported provider: {provider}") from e


def get_oauth_provider_model_ids(provider: str, *, dynamic: bool = True) -> tuple[str, ...]:
    if dynamic and _dynamic_refresh_enabled():
        return discover_oauth_provider_model_ids(provider)
    return get_bundled_oauth_provider_model_ids(provider)
