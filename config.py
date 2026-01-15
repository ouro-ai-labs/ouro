"""Configuration management for the agentic system."""

import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuration for the agentic system."""

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

    # Memory Management Configuration
    MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "true").lower() == "true"
    MEMORY_MAX_CONTEXT_TOKENS = int(os.getenv("MEMORY_MAX_CONTEXT_TOKENS", "100000"))
    MEMORY_TARGET_TOKENS = int(os.getenv("MEMORY_TARGET_TOKENS", "50000"))
    MEMORY_COMPRESSION_THRESHOLD = int(os.getenv("MEMORY_COMPRESSION_THRESHOLD", "40000"))
    MEMORY_SHORT_TERM_SIZE = int(os.getenv("MEMORY_SHORT_TERM_SIZE", "100"))
    MEMORY_COMPRESSION_RATIO = float(os.getenv("MEMORY_COMPRESSION_RATIO", "0.3"))

    # Logging Configuration
    LOG_DIR = os.getenv("LOG_DIR", "logs")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
    LOG_TO_FILE = os.getenv("LOG_TO_FILE", "true").lower() == "true"
    LOG_TO_CONSOLE = os.getenv("LOG_TO_CONSOLE", "false").lower() == "true"

    @classmethod
    def get_retry_config(cls):
        """Get retry configuration.

        Returns:
            RetryConfig instance with settings from environment variables
        """
        from llm.retry import RetryConfig

        return RetryConfig(
            max_retries=cls.RETRY_MAX_ATTEMPTS,
            initial_delay=cls.RETRY_INITIAL_DELAY,
            max_delay=cls.RETRY_MAX_DELAY,
            exponential_base=2.0,
            jitter=True,
        )

    @classmethod
    def get_memory_config(cls):
        """Get memory configuration.

        Returns:
            MemoryConfig instance with settings from environment variables
        """
        from memory import MemoryConfig

        return MemoryConfig(
            max_context_tokens=cls.MEMORY_MAX_CONTEXT_TOKENS,
            target_working_memory_tokens=cls.MEMORY_TARGET_TOKENS,
            compression_threshold=cls.MEMORY_COMPRESSION_THRESHOLD,
            short_term_message_count=cls.MEMORY_SHORT_TERM_SIZE,
            compression_ratio=cls.MEMORY_COMPRESSION_RATIO,
            enable_compression=cls.MEMORY_ENABLED,
        )

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
