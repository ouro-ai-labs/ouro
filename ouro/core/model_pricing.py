"""model pricing - updated at 2026-02-16"""

# Pricing is in USD per 1 million tokens.
# cache_read / cache_write are optional; when absent, falls back to input price.
#
# IMPORTANT: more-specific keys must appear BEFORE shorter prefixes so that
# the first substring match wins (e.g. "gpt-5-mini" before "gpt-5").

MODEL_PRICING = {
    # ── OpenAI ────────────────────────────────────────────────────────────────
    # GPT-5 family (cache read = 0.1× input)
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
    "gpt-5": {"input": 1.25, "output": 10.00, "cache_read": 0.125},
    # GPT-4.1 family (cache read = 0.25× input)
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60, "cache_read": 0.10},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40, "cache_read": 0.025},
    "gpt-4.1": {"input": 2.00, "output": 8.00, "cache_read": 0.50},
    # GPT-4o family (cache read = 0.5× input)
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075},
    "gpt-4o": {"input": 2.50, "output": 10.00, "cache_read": 1.25},
    # o-series reasoning models
    "o4-mini": {"input": 1.10, "output": 4.40, "cache_read": 0.275},
    "o3-pro": {"input": 20.00, "output": 80.00},
    "o3-mini": {"input": 1.10, "output": 4.40, "cache_read": 0.55},
    "o3": {"input": 2.00, "output": 8.00, "cache_read": 0.50},
    "o1-mini": {"input": 1.10, "output": 4.40},
    "o1": {"input": 15.00, "output": 60.00, "cache_read": 7.50},
    # ── Anthropic (cache read = 0.1× input, cache write = 1.25× input) ───────
    "claude-opus-4-6": {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-5": {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-sonnet-4-5": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-haiku-4-5": {
        "input": 1.00,
        "output": 5.00,
        "cache_read": 0.10,
        "cache_write": 1.25,
    },
    "claude-opus-4-1": {
        "input": 15.00,
        "output": 75.00,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    "claude-sonnet-4": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-4": {
        "input": 15.00,
        "output": 75.00,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    "claude-haiku-3": {"input": 0.25, "output": 1.25, "cache_read": 0.025, "cache_write": 0.3125},
    "claude-3-5-sonnet": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-3-5-haiku": {
        "input": 0.80,
        "output": 4.00,
        "cache_read": 0.08,
        "cache_write": 1.00,
    },
    "claude-3-opus": {
        "input": 15.00,
        "output": 75.00,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    # ── Google Gemini (cache read = 0.1× input) ──────────────────────────────
    "gemini-3-pro": {"input": 2.00, "output": 12.00, "cache_read": 0.20},
    "gemini-3-flash": {"input": 0.50, "output": 3.00, "cache_read": 0.05},
    "gemini-2-5-pro": {"input": 1.25, "output": 10.00, "cache_read": 0.125},
    "gemini-2-5-flash-lite": {"input": 0.10, "output": 0.40, "cache_read": 0.01},
    "gemini-2-5-flash": {"input": 0.30, "output": 2.50, "cache_read": 0.03},
    "gemini-2-0-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-2-0-flash": {"input": 0.10, "output": 0.40},
    "gemini-1-5-pro": {"input": 1.25, "output": 5.00, "cache_read": 0.3125},
    "gemini-1-5-flash": {"input": 0.075, "output": 0.30, "cache_read": 0.01875},
    # ── DeepSeek (cache read = 0.1× input) ────────────────────────────────────
    # V3.2 unified pricing for both chat and reasoner
    "deepseek-chat": {"input": 0.28, "output": 0.42, "cache_read": 0.028},
    "deepseek-reasoner": {"input": 0.28, "output": 0.42, "cache_read": 0.028},
    "deepseek-v3": {"input": 0.28, "output": 0.42, "cache_read": 0.028},
    # ── xAI Grok ──────────────────────────────────────────────────────────────
    "grok-4-fast": {"input": 0.20, "output": 0.50, "cache_read": 0.05},
    "grok-4": {"input": 3.00, "output": 15.00, "cache_read": 0.75},
    "grok-3-mini": {"input": 0.30, "output": 0.50, "cache_read": 0.07},
    "grok-3": {"input": 3.00, "output": 15.00, "cache_read": 0.75},
    "grok-code-fast": {"input": 0.20, "output": 1.50, "cache_read": 0.02},
    # ── Mistral ───────────────────────────────────────────────────────────────
    "mistral-large-3": {"input": 0.50, "output": 1.50},
    "mistral-large-2": {"input": 2.00, "output": 6.00},
    "mistral-medium-3": {"input": 0.40, "output": 2.00},
    "mistral-small-3": {"input": 0.06, "output": 0.18, "cache_read": 0.03},
    "devstral": {"input": 0.05, "output": 0.22, "cache_read": 0.025},
    "codestral": {"input": 0.30, "output": 0.90},
    "mistral-nemo": {"input": 0.02, "output": 0.04},
    # ── Kimi / Moonshot AI (cache read = 0.25× input) ────────────────────────
    "kimi-k2-5": {"input": 0.60, "output": 3.00, "cache_read": 0.15},
    "kimi-k2": {"input": 0.60, "output": 2.50, "cache_read": 0.15},
    # ── MiniMax ───────────────────────────────────────────────────────────────
    "minimax-m2.5": {"input": 0.30, "output": 1.20},
    "minimax-m2": {"input": 0.26, "output": 1.00, "cache_read": 0.03},
    "minimax-m1": {"input": 0.40, "output": 2.20},
    "minimax-01": {"input": 0.20, "output": 1.10},
    # ── GLM / Zhipu AI (cache read ≈ 0.2× input) ─────────────────────────────
    "glm-5-code": {"input": 1.20, "output": 5.00, "cache_read": 0.30},
    "glm-5": {"input": 1.00, "output": 3.20, "cache_read": 0.20},
    "glm-4.7-flashx": {"input": 0.07, "output": 0.40, "cache_read": 0.01},
    "glm-4.7": {"input": 0.60, "output": 2.20, "cache_read": 0.11},
    "glm-4.5-airx": {"input": 1.10, "output": 4.50, "cache_read": 0.22},
    "glm-4.5-air": {"input": 0.20, "output": 1.10, "cache_read": 0.03},
    "glm-4.5-x": {"input": 2.20, "output": 8.90, "cache_read": 0.45},
    "glm-4.5": {"input": 0.60, "output": 2.20, "cache_read": 0.11},
    "glm-4.6": {"input": 0.60, "output": 2.20, "cache_read": 0.11},
    # ── Default fallback ──────────────────────────────────────────────────────
    "default": {"input": 0.55, "output": 2.19},
}
