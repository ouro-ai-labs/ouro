import asyncio

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
