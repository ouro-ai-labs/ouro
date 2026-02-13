"""Configuration management for the agentic system."""

import os
import random

# Define path constants directly to avoid circular imports with utils
# (utils.terminal_ui imports Config, and utils.runtime is in the utils package)
_RUNTIME_DIR = os.path.join(os.path.expanduser("~"), ".ouro")
_CONFIG_FILE = os.path.join(_RUNTIME_DIR, "config")

# Default configuration template
_DEFAULT_CONFIG = """\
# ouro Configuration
#
# NOTE: Model configuration lives in `~/.ouro/models.yaml`.
# This file controls non-model runtime settings only.

TOOL_TIMEOUT=600
MAX_ITERATIONS=1000

# Ralph Loop (outer verification loop — re-checks task completion)
# RALPH_LOOP_MAX_ITERATIONS=3
"""


def _load_config(path: str) -> dict[str, str]:
    """Parse a KEY=VALUE config file, skipping comments and blank lines."""
    cfg: dict[str, str] = {}
    if not os.path.isfile(path):
        return cfg
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            # Strip inline comments (# ...) from the value
            if "#" in value:
                value = value[: value.index("#")]
            cfg[key.strip()] = value.strip()
    return cfg


def _ensure_config():
    """Ensure ~/.ouro/config exists, create with defaults if not."""
    if not os.path.exists(_CONFIG_FILE):
        os.makedirs(_RUNTIME_DIR, exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(_DEFAULT_CONFIG)


# Ensure config exists and load it
_ensure_config()
_cfg = _load_config(_CONFIG_FILE)


def get_raw_config() -> dict[str, str]:
    """Get the raw config dictionary.

    Returns:
        Dictionary of config key-value pairs
    """
    return _cfg.copy()


class Config:
    """Configuration for the agentic system.

    All configuration is centralized here. Access config values directly via Config.XXX.
    """

    # Model configuration is handled by `~/.ouro/models.yaml` via ModelManager.
    # `~/.ouro/config` controls non-model runtime settings only.
    TOOL_TIMEOUT = float(_cfg.get("TOOL_TIMEOUT", "600"))

    # Agent Configuration
    MAX_ITERATIONS = int(_cfg.get("MAX_ITERATIONS", "1000"))

    # Ralph Loop (outer verification loop)
    RALPH_LOOP_MAX_ITERATIONS = int(_cfg.get("RALPH_LOOP_MAX_ITERATIONS", "3"))

    # Retry Configuration
    RETRY_MAX_ATTEMPTS = int(_cfg.get("RETRY_MAX_ATTEMPTS", "3"))
    RETRY_INITIAL_DELAY = float(_cfg.get("RETRY_INITIAL_DELAY", "1.0"))
    RETRY_MAX_DELAY = float(_cfg.get("RETRY_MAX_DELAY", "60.0"))
    RETRY_EXPONENTIAL_BASE = 2.0
    RETRY_JITTER = True

    # Memory Management Configuration
    MEMORY_ENABLED = _cfg.get("MEMORY_ENABLED", "true").lower() == "true"
    MEMORY_COMPRESSION_THRESHOLD = int(_cfg.get("MEMORY_COMPRESSION_THRESHOLD", "60000"))
    MEMORY_SHORT_TERM_SIZE = int(_cfg.get("MEMORY_SHORT_TERM_SIZE", "100"))
    MEMORY_SHORT_TERM_MIN_SIZE = int(_cfg.get("MEMORY_SHORT_TERM_MIN_SIZE", "6"))
    MEMORY_COMPRESSION_RATIO = float(_cfg.get("MEMORY_COMPRESSION_RATIO", "0.3"))
    MEMORY_PRESERVE_SYSTEM_PROMPTS = True

    # Long-term Memory
    LONG_TERM_MEMORY_ENABLED = _cfg.get("LONG_TERM_MEMORY_ENABLED", "false").lower() == "true"
    LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD = int(
        _cfg.get("LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", "5000")
    )

    # Logging Configuration
    # Note: Logging is now controlled via --verbose flag
    # LOG_DIR is now ~/.ouro/logs/ (see utils.runtime)
    LOG_LEVEL = _cfg.get("LOG_LEVEL", "DEBUG").upper()

    # TUI Configuration
    TUI_THEME = _cfg.get("TUI_THEME", "dark")  # "dark" or "light"
    TUI_SHOW_THINKING = _cfg.get("TUI_SHOW_THINKING", "true").lower() == "true"
    TUI_THINKING_MAX_PREVIEW = int(_cfg.get("TUI_THINKING_MAX_PREVIEW", "300"))
    TUI_STATUS_BAR = _cfg.get("TUI_STATUS_BAR", "true").lower() == "true"
    TUI_COMPACT_MODE = _cfg.get("TUI_COMPACT_MODE", "false").lower() == "true"

    # Email Notification Configuration (Resend)
    RESEND_API_KEY = _cfg.get("RESEND_API_KEY") or ""
    NOTIFY_EMAIL_FROM = _cfg.get("NOTIFY_EMAIL_FROM") or ""

    @classmethod
    def get_retry_delay(cls, attempt: int) -> float:
        """Calculate delay for a given retry attempt using exponential backoff.

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        # Calculate exponential backoff
        delay = min(
            cls.RETRY_INITIAL_DELAY * (cls.RETRY_EXPONENTIAL_BASE**attempt),
            cls.RETRY_MAX_DELAY,
        )

        # Add jitter to avoid thundering herd
        if cls.RETRY_JITTER:
            delay = delay * (0.5 + random.random())

        return delay

    @classmethod
    def validate(cls):
        """Validate required configuration.

        Raises:
            ValueError: If required configuration is missing
        """
        # Model configuration is handled by `~/.ouro/models.yaml` via ModelManager.
        # `~/.ouro/config` is used for non-model runtime settings only.
        return
