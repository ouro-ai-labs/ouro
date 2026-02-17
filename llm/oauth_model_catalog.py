"""OAuth model catalog used to seed `~/.ouro/models.yaml` after login.

This file is intentionally deterministic and runtime-offline.

To refresh from pi-ai's latest published model registry, run:

    python scripts/update_oauth_model_catalog.py
"""

from __future__ import annotations

PI_AI_VERSION = "0.52.12"
PI_AI_PROVIDER_ID = "openai-codex"

# Synced from pi-ai openai-codex provider model IDs, filtered to those supported by
# the pinned LiteLLM chatgpt provider, and mapped to ouro's chatgpt/* namespace.
OAUTH_PROVIDER_MODEL_IDS: dict[str, tuple[str, ...]] = {
    "chatgpt": (
        "chatgpt/gpt-5.1",
        "chatgpt/gpt-5.1-codex-max",
        "chatgpt/gpt-5.1-codex-mini",
        "chatgpt/gpt-5.2",
        "chatgpt/gpt-5.2-codex",
    ),
}


def get_oauth_provider_model_ids(provider: str) -> tuple[str, ...]:
    try:
        return OAUTH_PROVIDER_MODEL_IDS[provider]
    except KeyError as e:
        raise ValueError(f"Unsupported provider: {provider}") from e
