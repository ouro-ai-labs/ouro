"""Tests for the Feishu WebSocket channel implementation."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.channel.base import IncomingMessage, OutgoingMessage

# ---------------------------------------------------------------------------
# Helpers — build SDK-style event objects without importing lark_oapi
# ---------------------------------------------------------------------------


def _make_sdk_event(
    text: str = "hello",
    chat_id: str = "oc_abc123",
    message_id: str = "msg_001",
    user_id: str = "ou_user1",
    message_type: str = "text",
) -> MagicMock:
    """Build a mock P2ImMessageReceiveV1 object matching lark SDK structure."""
    sender_id = MagicMock()
    sender_id.open_id = user_id

    sender = MagicMock()
    sender.sender_id = sender_id

    msg = MagicMock()
    msg.chat_id = chat_id
    msg.message_id = message_id
    msg.message_type = message_type
    msg.content = json.dumps({"text": text})

    event = MagicMock()
    event.message = msg
    event.sender = sender

    data = MagicMock()
    data.event = event
    return data


# ---------------------------------------------------------------------------
# Fixture: import FeishuChannel with lark_oapi mocked out
# ---------------------------------------------------------------------------


@pytest.fixture
def _mock_lark():
    """Patch lark_oapi so FeishuChannel can be imported without the real SDK."""
    mock_lark = MagicMock()
    # lark.Client.builder().app_id().app_secret().build()
    builder = MagicMock()
    builder.app_id.return_value = builder
    builder.app_secret.return_value = builder
    builder.build.return_value = MagicMock()
    mock_lark.Client.builder.return_value = builder

    # EventDispatcherHandler.builder().register_p2_im_message_receive_v1().build()
    handler_builder = MagicMock()
    handler_builder.register_p2_im_message_receive_v1.return_value = handler_builder
    handler_builder.build.return_value = MagicMock()
    mock_lark.EventDispatcherHandler.builder.return_value = handler_builder

    # lark.ws.Client — capture constructor args
    mock_ws_client = MagicMock()
    mock_lark.ws.Client.return_value = mock_ws_client

    mock_lark.LogLevel.WARNING = 3

    with (
        patch.dict("sys.modules", {"lark_oapi": mock_lark, "lark_oapi.api.im.v1": MagicMock()}),
        patch("config.Config") as mock_config,
    ):
        mock_config.FEISHU_APP_ID = "test_app_id"
        mock_config.FEISHU_APP_SECRET = "test_app_secret"

        # Re-import so the patched modules are used.
        import importlib

        import bot.channel.feishu as feishu_mod

        importlib.reload(feishu_mod)

        yield feishu_mod, mock_lark


@pytest.fixture
def channel(_mock_lark):
    feishu_mod, _ = _mock_lark
    return feishu_mod.FeishuChannel()


# ---------------------------------------------------------------------------
# _on_message handler tests
# ---------------------------------------------------------------------------


async def test_on_message_dispatches_text(channel):
    """The SDK callback should invoke the message_callback with an IncomingMessage."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    channel._loop = asyncio.get_running_loop()

    data = _make_sdk_event(text="hello world", chat_id="oc_1", message_id="m1", user_id="u1")
    channel._on_message(data)

    # Give the scheduled coroutine a chance to run.
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].text == "hello world"
    assert received[0].channel == "feishu"
    assert received[0].conversation_id == "oc_1"
    assert received[0].user_id == "u1"
    assert received[0].message_id == "m1"


async def test_on_message_ignores_non_text(channel):
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    channel._loop = asyncio.get_running_loop()

    data = _make_sdk_event(message_type="image")
    channel._on_message(data)
    await asyncio.sleep(0.05)

    assert len(received) == 0


async def test_on_message_ignores_empty_text(channel):
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    channel._loop = asyncio.get_running_loop()

    data = _make_sdk_event(text="   ")
    channel._on_message(data)
    await asyncio.sleep(0.05)

    assert len(received) == 0


async def test_on_message_no_callback(channel):
    """No crash when callback is None."""
    channel._callback = None
    data = _make_sdk_event()
    channel._on_message(data)  # should not raise


async def test_on_message_none_event(channel):
    """No crash when event is None."""
    channel._callback = AsyncMock()
    channel._loop = asyncio.get_running_loop()

    data = MagicMock()
    data.event = None
    channel._on_message(data)  # should not raise


# ---------------------------------------------------------------------------
# send_message tests
# ---------------------------------------------------------------------------


async def test_send_message_calls_api(channel):
    """send_message should call the sync _send_sync via to_thread."""
    channel._send_sync = MagicMock()

    msg = OutgoingMessage(conversation_id="oc_1", text="hi")
    with patch("bot.channel.feishu.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        await channel.send_message(msg)
        mock_to_thread.assert_called_once_with(channel._send_sync, msg)


# ---------------------------------------------------------------------------
# start / stop lifecycle
# ---------------------------------------------------------------------------


async def test_start_spawns_thread(channel, _mock_lark):
    """start() should create a daemon thread running ws_client.start."""
    _, mock_lark = _mock_lark

    cb = AsyncMock()
    with patch("bot.channel.feishu.threading.Thread") as MockThread:
        mock_thread_instance = MagicMock()
        MockThread.return_value = mock_thread_instance

        await channel.start(cb)

        MockThread.assert_called_once()
        assert MockThread.call_args[1]["daemon"] is True
        mock_thread_instance.start.assert_called_once()

    assert channel._callback is cb


async def test_stop_clears_state(channel):
    channel._callback = AsyncMock()
    channel._loop = asyncio.get_running_loop()
    channel._ws_client = MagicMock()

    await channel.stop()

    assert channel._callback is None
    assert channel._loop is None
    assert channel._ws_client is None
