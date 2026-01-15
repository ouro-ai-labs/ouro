"""Logging configuration for the agentic loop system."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

# Global flag to track if logging has been initialized
_logging_initialized = False
_log_file_path = None


def setup_logger(
    log_dir: Optional[str] = None,
    log_level: str = "DEBUG",
    log_to_file: bool = True,
    log_to_console: bool = False,
) -> None:
    """Configure the logging system globally.

    This should be called once at the start of the application.

    Args:
        log_dir: Directory to store log files (default: from Config.LOG_DIR)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: Whether to log to file
        log_to_console: Whether to log to console
    """
    global _logging_initialized, _log_file_path

    if _logging_initialized:
        return

    # Get configuration from Config if not provided
    if log_dir is None:
        try:
            from config import Config

            log_dir = Config.LOG_DIR
            log_level = Config.LOG_LEVEL
            log_to_file = Config.LOG_TO_FILE
            log_to_console = Config.LOG_TO_CONSOLE
        except ImportError:
            log_dir = "logs"

    # Set root logger level
    level = getattr(logging, log_level.upper(), logging.DEBUG)
    logging.root.setLevel(level)

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Add file handler if enabled
    if log_to_file:
        log_path = Path(log_dir)
        log_path.mkdir(exist_ok=True, parents=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_path / f"agentic_loop_{timestamp}.log"
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
    logging.info(
        f"Logging initialized. Level: {log_level}, File: {_log_file_path if log_to_file else 'disabled'}"
    )


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a module.

    This will automatically initialize logging if not already done.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    if not _logging_initialized:
        setup_logger()

    return logging.getLogger(name)


def get_log_file_path() -> Optional[str]:
    """Get the path to the current log file.

    Returns:
        Path to log file, or None if logging to file is disabled
    """
    return _log_file_path
