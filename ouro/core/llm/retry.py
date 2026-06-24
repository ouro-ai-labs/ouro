"""Retry utilities for LLM API calls using tenacity."""

import asyncio
from typing import Callable, TypeVar

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt
from tenacity.wait import wait_base

from ouro.config import Config
from ouro.core.log import get_logger

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

    if isinstance(error, httpx.TimeoutException | httpx.NetworkError | httpx.RemoteProtocolError):
        return True

    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        return status_code in {408, 409, 425, 429, 500, 502, 503, 504}

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
        # httpx/httpcore can surface upstream disconnects as
        # RemoteProtocolError("Server disconnected without sending a response")
        # without wrapping them in LiteLLM's APIConnectionError. Treat these as
        # transient transport failures so the normal retry policy applies.
        "server disconnected",
        "disconnected without sending",
        "remote protocol error",
        "remoteprotocolerror",
        "connection closed",
        "connection reset",
        "connection aborted",
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


def _boxed_retry_message(
    *, error_type: str, error: BaseException, delay: float, attempt: int
) -> str:
    """Format retry notices as a compact terminal-friendly box.

    Keep this in core without importing the TUI layer, but mirror the visual
    structure used by terminal_ui.print_tool_call(): rounded corners, a
    left-aligned title, and indented key/value rows.
    """
    lines = [
        f"  error: {error}",
        f"  retryIn: {delay:.1f}s",
        f"  attempt: {attempt}/{Config.RETRY_MAX_ATTEMPTS + 1}",
    ]
    width = max(len(line) for line in lines)
    title = f" Retry: {error_type} "
    top = f"╭─{title}{'─' * max(width - len(title), 0)}╮"
    body = [f"│ {line.ljust(width)} │" for line in lines]
    bottom = f"╰{'─' * (width + 2)}╯"
    return "\n".join([top, *body, bottom])


def _log_before_sleep(retry_state) -> None:
    error = retry_state.outcome.exception() if retry_state.outcome else None
    if not error:
        return

    # The first transient failure is common and usually self-heals; keep the CLI
    # quiet unless a second (or later) retry is needed.
    if retry_state.attempt_number <= 1:
        return

    error_type = "Rate limit" if is_rate_limit_error(error) else "Retryable"
    delay = _ConfigBackoff()(retry_state)
    logger.warning(
        _boxed_retry_message(
            error_type=error_type,
            error=error,
            delay=delay,
            attempt=retry_state.attempt_number,
        )
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
