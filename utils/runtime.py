"""Runtime directory management for AgenticLoop.

All runtime data is stored under .aloop/ directory:
- config: Configuration file (created by config.py on first import)
- db/memory.db: SQLite database for memory persistence
- logs/: Log files (only created with --verbose)
- history: Interactive mode command history
- exports/: Memory dump exports
"""

import os

RUNTIME_DIR = ".aloop"


def get_runtime_dir() -> str:
    """Get the runtime directory path.

    Returns:
        Path to .aloop directory
    """
    return RUNTIME_DIR


def get_config_file() -> str:
    """Get the configuration file path.

    Returns:
        Path to .aloop/config
    """
    return os.path.join(RUNTIME_DIR, "config")


def get_db_path() -> str:
    """Get the database file path.

    Returns:
        Path to .aloop/db/memory.db
    """
    return os.path.join(RUNTIME_DIR, "db", "memory.db")


def get_log_dir() -> str:
    """Get the log directory path.

    Returns:
        Path to .aloop/logs/
    """
    return os.path.join(RUNTIME_DIR, "logs")


def get_history_file() -> str:
    """Get the command history file path.

    Returns:
        Path to .aloop/history
    """
    return os.path.join(RUNTIME_DIR, "history")


def get_exports_dir() -> str:
    """Get the exports directory path.

    Returns:
        Path to .aloop/exports/
    """
    return os.path.join(RUNTIME_DIR, "exports")


def ensure_runtime_dirs(create_logs: bool = False) -> None:
    """Ensure runtime directories exist.

    Creates:
    - .aloop/db/
    - .aloop/exports/
    - .aloop/logs/ (only if create_logs=True)

    Note: .aloop/config is created by config.py on first import.

    Args:
        create_logs: Whether to create the logs directory (for --verbose mode)
    """
    os.makedirs(os.path.join(RUNTIME_DIR, "db"), exist_ok=True)
    os.makedirs(os.path.join(RUNTIME_DIR, "exports"), exist_ok=True)

    if create_logs:
        os.makedirs(os.path.join(RUNTIME_DIR, "logs"), exist_ok=True)
