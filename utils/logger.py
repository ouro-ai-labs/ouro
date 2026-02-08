"""Logging configuration for ouro."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .runtime import get_log_dir

# Global flag to track if logging has been initialized
_logging_initialized = False
_log_file_path = None


def setup_logger(
    log_dir: Optional[str] = None,
    log_level: Optional[str] = None,
    log_to_console: bool = False,
) -> None:
    """Configure the logging system globally.

    This should be called once at the start of the application when --verbose is enabled.
    Logging is written to .ouro/logs/ by default.

    Args:
        log_dir: Directory to store log files (default: .ouro/logs/)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_console: Whether to also log to console
    """
    global _logging_initialized, _log_file_path

    if _logging_initialized:
        return

    # Use runtime log directory by default
    if log_dir is None:
        log_dir = get_log_dir()

    # Get log level from Config if not provided
    if log_level is None:
        try:
            from config import Config

            log_level = Config.LOG_LEVEL
        except ImportError:
            log_level = "DEBUG"

    # Set root logger level
    level = getattr(logging, log_level.upper(), logging.DEBUG)
    logging.root.setLevel(level)

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Add file handler (always enabled when setup_logger is called)
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True, parents=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_path / f"ouro_{timestamp}.log"
    _log_file_path = str(log_file)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logging.root.addHandler(file_handler)

    # Add console handler if enabled
    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(formatter)
        logging.root.addHandler(console_handler)

    _logging_initialized = True

    # Log initialization message
    logging.info(f"Logging initialized. Level: {log_level}, File: {_log_file_path}")


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a module.

    Note: This no longer auto-initializes logging. Logging is only enabled
    when --verbose flag is used and setup_logger() is called explicitly.
    Without verbose mode, logs go nowhere (NullHandler behavior).

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def get_log_file_path() -> Optional[str]:
    """Get the path to the current log file.

    Returns:
        Path to log file, or None if logging to file is disabled
    """
    return _log_file_path
