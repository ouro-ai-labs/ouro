"""model pricing - updated at 2026-01-24"""

# Pricing is in USD per 1 million tokens
# cache_read / cache_write are optional; when absent, falls back to input price.
MODEL_PRICING = {
    # --- OpenAI (cache read = 0.5× input, cache write = same as input) ---
    "gpt-5": {"input": 1.25, "output": 10.00, "cache_read": 0.625},
    "gpt-4.5": {"input": 75.00, "output": 150.00, "cache_read": 37.50},
    "gpt-4o": {"input": 2.50, "output": 10.00, "cache_read": 1.25},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075},
    "o1": {"input": 15.00, "output": 60.00, "cache_read": 7.50},
    "o1-mini": {"input": 1.10, "output": 4.40, "cache_read": 0.55},
    "o3": {"input": 2.00, "output": 8.00, "cache_read": 1.00},
    "o3-mini": {"input": 0.55, "output": 2.20, "cache_read": 0.275},
    "o4-mini": {"input": 1.10, "output": 4.40, "cache_read": 0.55},
    # --- Anthropic (cache read = 0.1× input, cache write = 1.25× input) ---
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
    "claude-3-5-sonnet-20241022": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-3-5-haiku-20241022": {
        "input": 0.80,
        "output": 4.00,
        "cache_read": 0.08,
        "cache_write": 1.00,
    },
    "claude-3-opus-20240229": {
        "input": 15.00,
        "output": 75.00,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    # --- Google Gemini (cache read = 0.25× input) ---
    "gemini-3-pro": {"input": 2.00, "output": 12.00, "cache_read": 0.50},
    "gemini-3-pro-preview": {"input": 2.00, "output": 12.00, "cache_read": 0.50},
    "gemini-3-flash": {"input": 0.50, "output": 3.00, "cache_read": 0.125},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00, "cache_read": 0.125},
    "gemini-2-5-pro": {"input": 1.25, "output": 10.00, "cache_read": 0.3125},
    "gemini-2-5-flash": {"input": 0.30, "output": 2.50, "cache_read": 0.075},
    "gemini-2-5-flash-lite": {"input": 0.10, "output": 0.40, "cache_read": 0.025},
    "gemini-2-0-flash": {"input": 0.10, "output": 0.40, "cache_read": 0.025},
    "gemini-2-0-flash-lite": {"input": 0.075, "output": 0.30, "cache_read": 0.01875},
    "gemini-1-5-pro": {"input": 1.25, "output": 5.00, "cache_read": 0.3125},
    "gemini-1-5-flash": {"input": 0.075, "output": 0.30, "cache_read": 0.01875},
    # --- DeepSeek (cache read = 0.1× input) ---
    "deepseek-v3": {"input": 0.14, "output": 0.28, "cache_read": 0.014},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19, "cache_read": 0.055},
    # --- xAI (Grok) ---
    "grok-4": {"input": 3.00, "output": 15.00},
    "grok-4-fast": {"input": 0.20, "output": 0.50},
    # --- Mistral ---
    "mistral-large-2": {"input": 2.00, "output": 6.00},
    "mistral-small-3": {"input": 0.10, "output": 0.30},
    # --- Default ---
    "default": {"input": 0.55, "output": 2.19},
}
