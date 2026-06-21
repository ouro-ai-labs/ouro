import asyncio

import httpx

from ouro.core.llm.retry import is_retryable_error


class CustomError(Exception):
    pass


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
