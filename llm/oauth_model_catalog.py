"""OAuth model catalog used to seed `~/.ouro/models.yaml` after login.

This file is intentionally deterministic and runtime-offline.

To refresh the chatgpt provider from pi-ai's latest published model registry, run:

    python scripts/update_oauth_model_catalog.py

The copilot provider list is curated manually from GitHub's supported-models
reference. Refresh from:
    https://docs.github.com/en/copilot/reference/ai-models/supported-models
Only chat-mode models are included; `/responses`-mode codex variants are omitted
because the adapter routes through LiteLLM's `acompletion` endpoint.
"""

from __future__ import annotations

PI_AI_VERSION = "0.52.12"
PI_AI_PROVIDER_ID = "openai-codex"

# Synced from pi-ai openai-codex provider model IDs, filtered to those supported by
# the pinned LiteLLM chatgpt provider, and mapped to ouro's chatgpt/* namespace.
# Copilot entries target LiteLLM's built-in `github_copilot/*` namespace and cover
# the chat-capable models exposed to Copilot subscribers.
OAUTH_PROVIDER_MODEL_IDS: dict[str, tuple[str, ...]] = {
    "chatgpt": (
        "chatgpt/gpt-5.1",
        "chatgpt/gpt-5.1-codex-max",
        "chatgpt/gpt-5.1-codex-mini",
        "chatgpt/gpt-5.2",
        "chatgpt/gpt-5.2-codex",
    ),
    "copilot": (
        # Anthropic (GA)
        "github_copilot/claude-opus-4.7",
        "github_copilot/claude-opus-4.6",
        "github_copilot/claude-sonnet-4.6",
        "github_copilot/claude-sonnet-4.5",
        "github_copilot/claude-haiku-4.5",
        # OpenAI (GA)
        "github_copilot/gpt-5.4",
        "github_copilot/gpt-5.4-mini",
        "github_copilot/gpt-5.2",
        # Google (GA + preview)
        "github_copilot/gemini-2.5-pro",
        "github_copilot/gemini-3.1-pro",
        # xAI (GA)
        "github_copilot/grok-code-fast-1",
    ),
}


def get_oauth_provider_model_ids(provider: str) -> tuple[str, ...]:
    try:
        return OAUTH_PROVIDER_MODEL_IDS[provider]
    except KeyError as e:
        raise ValueError(f"Unsupported provider: {provider}") from e
