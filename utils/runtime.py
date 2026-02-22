"""Runtime directory management for ouro.

All runtime data is stored under ~/.ouro/ directory:
- config: Configuration file (created by config.py on first import)
- sessions/: YAML-based session persistence
- logs/: Log files (only created with --verbose)
- history: Interactive mode command history
"""

import os

RUNTIME_DIR = os.path.join(os.path.expanduser("~"), ".ouro")


def get_runtime_dir() -> str:
    """Get the runtime directory path.

    Returns:
        Path to ~/.ouro directory
    """
    return RUNTIME_DIR


def get_config_file() -> str:
    """Get the configuration file path.

    Returns:
        Path to ~/.ouro/config
    """
    return os.path.join(RUNTIME_DIR, "config")


def get_sessions_dir() -> str:
    """Get the sessions directory path.

    Returns:
        Path to ~/.ouro/sessions/
    """
    override = os.environ.get("OURO_SESSIONS_DIR")
    if override and override.strip():
        return os.path.expanduser(override.strip())
    return os.path.join(RUNTIME_DIR, "sessions")


def get_log_dir() -> str:
    """Get the log directory path.

    Returns:
        Path to ~/.ouro/logs/
    """
    return os.path.join(RUNTIME_DIR, "logs")


def get_memory_dir() -> str:
    """Get the long-term memory directory path.

    Returns:
        Path to ~/.ouro/memory/
    """
    return os.path.join(RUNTIME_DIR, "memory")


def get_history_file() -> str:
    """Get the command history file path.

    Returns:
        Path to ~/.ouro/history
    """
    return os.path.join(RUNTIME_DIR, "history")


_BOT_DIR = os.path.join(RUNTIME_DIR, "bot")


def get_bot_sessions_dir() -> str:
    """Get the bot sessions directory path.

    Returns:
        Path to ~/.ouro/bot/sessions/
    """
    return os.path.join(_BOT_DIR, "sessions")


def get_bot_memory_dir() -> str:
    """Get the bot long-term memory directory path.

    Returns:
        Path to ~/.ouro/bot/memory/
    """
    return os.path.join(_BOT_DIR, "memory")


def get_bot_skills_dir() -> str:
    """Get the bot skills directory path.

    Returns:
        Path to ~/.ouro/bot/skills/
    """
    return os.path.join(_BOT_DIR, "skills")


def ensure_bot_dirs() -> None:
    """Ensure bot-specific runtime directories exist.

    Creates:
    - ~/.ouro/bot/sessions/
    - ~/.ouro/bot/memory/
    - ~/.ouro/bot/skills/
    """
    for subdir in ("sessions", "memory", "skills"):
        os.makedirs(os.path.join(_BOT_DIR, subdir), exist_ok=True)


def ensure_runtime_dirs(create_logs: bool = False) -> None:
    """Ensure runtime directories exist.

    Creates:
    - ~/.ouro/sessions/
    - ~/.ouro/logs/ (only if create_logs=True)

    Note: ~/.ouro/config is created by config.py on first import.

    Args:
        create_logs: Whether to create the logs directory (for --verbose mode)
    """
    # Allow overriding sessions dir for restricted environments (e.g. sandboxed runs).
    os.makedirs(get_sessions_dir(), exist_ok=True)

    if create_logs:
        os.makedirs(get_log_dir(), exist_ok=True)
