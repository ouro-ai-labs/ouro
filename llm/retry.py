"""Retry utilities for LLM API calls with exponential backoff."""

import random
import time
from functools import wraps
from typing import Callable, TypeVar

from utils import get_logger

logger = get_logger(__name__)
T = TypeVar("T")


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_retries: int = 5,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
    ):
        """Initialize retry configuration.

        Args:
            max_retries: Maximum number of retry attempts
            initial_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            exponential_base: Base for exponential backoff
            jitter: Whether to add random jitter to delays
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for a given retry attempt.

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        # Calculate exponential backoff
        delay = min(self.initial_delay * (self.exponential_base**attempt), self.max_delay)

        # Add jitter to avoid thundering herd
        if self.jitter:
            delay = delay * (0.5 + random.random())

        return delay


def is_rate_limit_error(error: Exception) -> bool:
    """Check if an error is a rate limit error.

    Args:
        error: Exception to check

    Returns:
        True if this is a rate limit error
    """
    error_str = str(error).lower()

    # Common rate limit indicators
    rate_limit_indicators = [
        "429",
        "rate limit",
        "quota",
        "too many requests",
        "resourceexhausted",
    ]

    return any(indicator in error_str for indicator in rate_limit_indicators)


def is_retryable_error(error: Exception) -> bool:
    """Check if an error is retryable.

    Args:
        error: Exception to check

    Returns:
        True if this error should trigger a retry
    """
    # Rate limit errors are always retryable
    if is_rate_limit_error(error):
        return True

    error_str = str(error).lower()
    error_type = type(error).__name__

    # LiteLLM-specific errors
    if "RateLimitError" in error_type or "APIConnectionError" in error_type:
        return True

    # Other retryable errors
    retryable_indicators = [
        "timeout",
        "connection",
        "server error",
        "500",
        "502",
        "503",
        "504",
    ]

    return any(indicator in error_str for indicator in retryable_indicators)


def with_retry(config: RetryConfig = None):
    """Decorator to add retry logic with exponential backoff.

    Args:
        config: RetryConfig instance, uses defaults if None

    Returns:
        Decorator function
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Try to get config from instance (self) if available
            retry_config = config
            if retry_config is None and args and hasattr(args[0], "retry_config"):
                retry_config = args[0].retry_config
            if retry_config is None:
                retry_config = RetryConfig()

            last_error = None

            for attempt in range(retry_config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e

                    # Don't retry on last attempt
                    if attempt == retry_config.max_retries:
                        break

                    # Only retry if error is retryable
                    if not is_retryable_error(e):
                        raise

                    # Calculate delay
                    delay = retry_config.get_delay(attempt)

                    # Log retry attempt
                    error_type = "Rate limit" if is_rate_limit_error(e) else "Retryable"
                    logger.warning(f"{error_type} error: {str(e)}")
                    logger.warning(
                        f"Retrying in {delay:.1f}s... (attempt {attempt + 1}/{retry_config.max_retries})"
                    )

                    # Wait before retry
                    time.sleep(delay)

            # All retries exhausted
            raise last_error

        return wrapper

    return decorator


def retry_with_backoff(func: Callable[..., T], *args, config: RetryConfig = None, **kwargs) -> T:
    """Execute a function with retry logic.

    Args:
        func: Function to execute
        *args: Positional arguments for func
        config: RetryConfig instance
        **kwargs: Keyword arguments for func

    Returns:
        Result from func

    Raises:
        Last exception if all retries fail
    """
    if config is None:
        config = RetryConfig()

    decorated_func = with_retry(config)(func)
    return decorated_func(*args, **kwargs)
