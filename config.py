"""Configuration management for the agentic system."""

import os
import random

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuration for the agentic system.

    All configuration is centralized here. Access config values directly via Config.XXX.
    """

    # LiteLLM Model Configuration
    # Format: provider/model_name (e.g. "anthropic/claude-3-5-sonnet-20241022")
    LITELLM_MODEL = os.getenv("LITELLM_MODEL", "anthropic/claude-3-5-sonnet-20241022")

    # Common provider API keys (optional depending on provider)
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    # Optional LiteLLM Configuration
    LITELLM_API_BASE = os.getenv("LITELLM_API_BASE")
    LITELLM_DROP_PARAMS = os.getenv("LITELLM_DROP_PARAMS", "true").lower() == "true"
    LITELLM_TIMEOUT = int(os.getenv("LITELLM_TIMEOUT", "600"))

    # Agent Configuration
    MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "10"))

    # Retry Configuration
    RETRY_MAX_ATTEMPTS = int(os.getenv("RETRY_MAX_ATTEMPTS", "3"))
    RETRY_INITIAL_DELAY = float(os.getenv("RETRY_INITIAL_DELAY", "1.0"))
    RETRY_MAX_DELAY = float(os.getenv("RETRY_MAX_DELAY", "60.0"))
    RETRY_EXPONENTIAL_BASE = 2.0
    RETRY_JITTER = True

    # Memory Management Configuration
    MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "true").lower() == "true"
    MEMORY_COMPRESSION_THRESHOLD = int(os.getenv("MEMORY_COMPRESSION_THRESHOLD", "60000"))
    MEMORY_SHORT_TERM_SIZE = int(os.getenv("MEMORY_SHORT_TERM_SIZE", "100"))
    MEMORY_SHORT_TERM_MIN_SIZE = int(os.getenv("MEMORY_SHORT_TERM_MIN_SIZE", "6"))
    MEMORY_COMPRESSION_RATIO = float(os.getenv("MEMORY_COMPRESSION_RATIO", "0.3"))
    MEMORY_PRESERVE_SYSTEM_PROMPTS = True

    # Tool Result Processing Configuration
    TOOL_RESULT_STORAGE_THRESHOLD = int(os.getenv("TOOL_RESULT_STORAGE_THRESHOLD", "10000"))
    TOOL_RESULT_STORAGE_PATH = os.getenv("TOOL_RESULT_STORAGE_PATH")
    # Model for summarizing large tool results (e.g., "openai/gpt-4o-mini", "anthropic/claude-3-haiku-20240307")
    # If not set, LLM summarization is disabled and falls back to smart truncation
    TOOL_RESULT_SUMMARY_MODEL = os.getenv("TOOL_RESULT_SUMMARY_MODEL")

    # Tools that should never have their results truncated (comma-separated)
    TOOL_RESULT_BYPASS_TOOLS = os.getenv("TOOL_RESULT_BYPASS_TOOLS", "retrieve_tool_result").split(
        ","
    )

    # Logging Configuration
    LOG_DIR = os.getenv("LOG_DIR", "logs")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
    LOG_TO_FILE = os.getenv("LOG_TO_FILE", "true").lower() == "true"
    LOG_TO_CONSOLE = os.getenv("LOG_TO_CONSOLE", "false").lower() == "true"

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
        if not cls.LITELLM_MODEL:
            raise ValueError(
                "LITELLM_MODEL not set. Please set it in your .env file.\n"
                "Example: LITELLM_MODEL=anthropic/claude-3-5-sonnet-20241022"
            )

        # Validate common providers (LiteLLM supports many; only enforce the ones we document).
        provider = cls.LITELLM_MODEL.split("/", 1)[0].lower() if "/" in cls.LITELLM_MODEL else ""
        if provider == "anthropic" and not cls.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set. Please set it in your .env file.")
        if provider == "openai" and not cls.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set. Please set it in your .env file.")
        if provider == "gemini" and not cls.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not set. Please set it in your .env file.")
