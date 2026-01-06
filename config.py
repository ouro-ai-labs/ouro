"""Configuration management for the agentic system."""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuration for the agentic system."""

    # LLM Provider Configuration
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()

    # API Keys
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    # Model Configuration
    MODEL = os.getenv("MODEL")  # Optional, will use provider defaults if not set

    # Agent Configuration
    MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "10"))

    # Tool Configuration
    ENABLE_SHELL = os.getenv("ENABLE_SHELL", "false").lower() == "true"

    @classmethod
    def get_api_key(cls) -> str:
        """Get the appropriate API key based on the selected provider.

        Returns:
            API key for the selected provider

        Raises:
            ValueError: If API key is not set for the selected provider
        """
        if cls.LLM_PROVIDER == "anthropic":
            if not cls.ANTHROPIC_API_KEY:
                raise ValueError("ANTHROPIC_API_KEY not set")
            return cls.ANTHROPIC_API_KEY
        elif cls.LLM_PROVIDER == "openai":
            if not cls.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not set")
            return cls.OPENAI_API_KEY
        elif cls.LLM_PROVIDER == "gemini":
            if not cls.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY not set")
            return cls.GEMINI_API_KEY
        else:
            raise ValueError(f"Unknown LLM provider: {cls.LLM_PROVIDER}")

    @classmethod
    def get_default_model(cls) -> str:
        """Get the default model for the selected provider.

        Returns:
            Default model identifier
        """
        if cls.MODEL:
            return cls.MODEL

        # Provider-specific defaults
        defaults = {
            "anthropic": "claude-3-5-sonnet-20241022",
            "openai": "gpt-4o",
            "gemini": "gemini-1.5-pro",
        }

        return defaults.get(cls.LLM_PROVIDER, "")

    @classmethod
    def validate(cls):
        """Validate required configuration."""
        try:
            cls.get_api_key()
        except ValueError as e:
            raise ValueError(
                f"{e}. Please set it in your .env file or environment variables."
            )
