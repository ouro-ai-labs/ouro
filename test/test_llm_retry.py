import asyncio
import logging
from types import SimpleNamespace

import httpx

from ouro.core.llm.retry import _boxed_retry_message, _log_before_sleep, is_retryable_error


class CustomError(Exception):
    pass


class _Outcome:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    def exception(self) -> BaseException:
        return self._error


def _retry_state(attempt_number: int, error: BaseException) -> SimpleNamespace:
    return SimpleNamespace(attempt_number=attempt_number, outcome=_Outcome(error))


def test_server_disconnected_error_is_retryable() -> None:
    assert is_retryable_error(CustomError("Server disconnected without sending a response."))


def test_remote_protocol_disconnect_error_is_retryable() -> None:
    assert is_retryable_error(
        CustomError("httpcore.RemoteProtocolError: Server disconnected without sending a response.")
    )


def test_cancelled_error_is_not_retryable() -> None:
    assert not is_retryable_error(asyncio.CancelledError())


def test_httpx_connect_error_is_retryable_even_without_message() -> None:
    assert is_retryable_error(httpx.ConnectError(""))


def test_retryable_http_statuses_are_retryable() -> None:
    for status_code in (408, 409, 425, 429, 500, 502, 503, 504):
        response = httpx.Response(
            status_code, request=httpx.Request("POST", "https://example.test")
        )
        assert is_retryable_error(
            httpx.HTTPStatusError("failed", request=response.request, response=response)
        )


def test_non_retryable_http_statuses_are_not_retryable() -> None:
    for status_code in (400, 401, 403, 404, 422):
        response = httpx.Response(
            status_code, request=httpx.Request("POST", "https://example.test")
        )
        assert not is_retryable_error(
            httpx.HTTPStatusError("failed", request=response.request, response=response)
        )


def test_unknown_exception_is_not_retryable_by_default() -> None:
    assert not is_retryable_error(ValueError("bad request body"))


def test_log_before_sleep_suppresses_first_retry(caplog):
    with caplog.at_level(logging.WARNING, logger="ouro.core.llm.retry"):
        _log_before_sleep(_retry_state(1, RuntimeError("Server disconnected")))

    assert caplog.text == ""


def test_log_before_sleep_boxes_second_and_later_retries(caplog):
    error = RuntimeError("Server disconnected without sending a response.")

    with caplog.at_level(logging.WARNING, logger="ouro.core.llm.retry"):
        _log_before_sleep(_retry_state(2, error))

    assert "┌─ Retry" in caplog.text
    assert "│ Retryable error: Server disconnected without sending a response." in caplog.text
    assert "│ Retrying in" in caplog.text
    assert "(attempt 2/" in caplog.text
    assert "└" in caplog.text


def test_boxed_retry_message_contains_single_boxed_notice():
    message = _boxed_retry_message(
        error_type="Retryable",
        error=RuntimeError("Server disconnected without sending a response."),
        delay=1.0,
        attempt=2,
    )

    lines = message.splitlines()
    assert lines[0].startswith("┌─ Retry ─")
    assert lines[1].startswith("│ Retryable error: Server disconnected")
    assert lines[2].startswith("│ Retrying in 1.0s... (attempt 2/")
    assert lines[3].startswith("└")
