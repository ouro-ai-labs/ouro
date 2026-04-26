"""Retry utilities for LLM API calls using tenacity."""

import asyncio
from typing import Callable, TypeVar

from tenacity import retry, retry_if_exception, stop_after_attempt
from tenacity.wait import wait_base

from config import Config
from utils import get_logger

logger = get_logger(__name__)
T = TypeVar("T")


def is_rate_limit_error(error: BaseException) -> bool:
    """Check if an error is a rate limit error."""
    error_str = str(error).lower()
    rate_limit_indicators = [
        "429",
        "rate limit",
        "quota",
        "too many requests",
        "resourceexhausted",
    ]
    return any(indicator in error_str for indicator in rate_limit_indicators)


def is_retryable_error(error: BaseException) -> bool:
    """Check if an error is retryable."""
    if isinstance(error, asyncio.CancelledError):
        return False

    if is_rate_limit_error(error):
        return True

    error_str = str(error).lower()
    error_type = type(error).__name__

    if "RateLimitError" in error_type or "APIConnectionError" in error_type:
        return True

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


class _ConfigBackoff(wait_base):
    def __call__(self, retry_state) -> float:
        attempt = max(retry_state.attempt_number - 1, 0)
        return Config.get_retry_delay(attempt)


def _log_before_sleep(retry_state) -> None:
    error = retry_state.outcome.exception() if retry_state.outcome else None
    if not error:
        return
    error_type = "Rate limit" if is_rate_limit_error(error) else "Retryable"
    delay = _ConfigBackoff()(retry_state)
    logger.warning(f"{error_type} error: {error}")
    logger.warning(
        "Retrying in %.1fs... (attempt %s/%s)",
        delay,
        retry_state.attempt_number,
        Config.RETRY_MAX_ATTEMPTS + 1,
    )


def with_retry():
    """Decorator to add async retry logic with exponential backoff.

    The total number of attempts is RETRY_MAX_ATTEMPTS + 1:
    - 1 initial attempt
    - RETRY_MAX_ATTEMPTS retry attempts (if initial fails)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        # stop_after_attempt counts total attempts, not retries
        # So for N retries, we need N+1 total attempts
        return retry(
            retry=retry_if_exception(is_retryable_error),
            stop=stop_after_attempt(Config.RETRY_MAX_ATTEMPTS + 1),
            wait=_ConfigBackoff(),
            reraise=True,
            before_sleep=_log_before_sleep,
        )(func)

    return decorator
