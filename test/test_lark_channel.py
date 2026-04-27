"""Tests for the Lark WebSocket channel implementation."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ouro.interfaces.bot.channel.base import IncomingMessage, OutgoingMessage

# ---------------------------------------------------------------------------
# Helpers — build SDK-style event objects without importing lark_oapi
# ---------------------------------------------------------------------------


def _make_mention(open_id: str, key: str = "@_user_1") -> MagicMock:
    """Build a mock mention entry."""
    m = MagicMock()
    m.id = MagicMock()
    m.id.open_id = open_id
    m.key = key
    return m


def _make_sdk_event(
    text: str = "hello",
    chat_id: str = "oc_abc123",
    message_id: str = "msg_001",
    user_id: str = "ou_user1",
    message_type: str = "text",
    chat_type: str = "p2p",
    mentions: list | None = None,
    content: str | None = None,
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
    msg.chat_type = chat_type
    msg.mentions = mentions
    if content is not None:
        msg.content = content
    elif message_type == "text":
        msg.content = json.dumps({"text": text})
    elif message_type == "image":
        msg.content = json.dumps({"image_key": "img_key_123"})
    else:
        msg.content = "{}"

    event = MagicMock()
    event.message = msg
    event.sender = sender

    data = MagicMock()
    data.event = event
    return data


# ---------------------------------------------------------------------------
# Fixture: import LarkChannel with lark_oapi mocked out
# ---------------------------------------------------------------------------


@pytest.fixture
def _mock_lark():
    """Patch lark_oapi so LarkChannel can be imported without the real SDK."""
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
        patch.dict(
            "sys.modules",
            {
                "lark_oapi": mock_lark,
                "lark_oapi.api.im.v1": MagicMock(),
                "lark_oapi.api.bot.v3": MagicMock(),
            },
        ),
        patch("ouro.config.Config") as mock_config,
    ):
        mock_config.LARK_APP_ID = "test_app_id"
        mock_config.LARK_APP_SECRET = "test_app_secret"

        # Re-import so the patched modules are used.
        import importlib

        import bot.channel.lark as lark_mod

        importlib.reload(lark_mod)

        yield lark_mod, mock_lark


@pytest.fixture
def channel(_mock_lark):
    lark_mod, _ = _mock_lark
    ch = lark_mod.LarkChannel()
    ch._bot_open_id = "bot_open_id_123"
    return ch


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
    assert received[0].channel == "lark"
    assert received[0].conversation_id == "oc_1"
    assert received[0].user_id == "u1"
    assert received[0].message_id == "m1"


async def test_on_message_ignores_unsupported_type(channel):
    """Non-text, non-image message types should be ignored."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    channel._loop = asyncio.get_running_loop()

    data = _make_sdk_event(message_type="audio")
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
# @ Mention filtering tests
# ---------------------------------------------------------------------------


async def test_on_message_group_mention_dispatches(channel):
    """Group chat with bot mention should dispatch."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    channel._loop = asyncio.get_running_loop()

    mention = _make_mention(open_id="bot_open_id_123", key="@_user_1")
    data = _make_sdk_event(
        text="@_user_1 what is this?",
        chat_type="group",
        mentions=[mention],
    )
    channel._on_message(data)
    await asyncio.sleep(0.05)

    assert len(received) == 1


async def test_on_message_group_no_mention_ignored(channel):
    """Group chat without bot mention should be ignored."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    channel._loop = asyncio.get_running_loop()

    data = _make_sdk_event(
        text="hey everyone",
        chat_type="group",
        mentions=[],
    )
    channel._on_message(data)
    await asyncio.sleep(0.05)

    assert len(received) == 0


async def test_on_message_dm_always_dispatches(channel):
    """DM (p2p) messages should always dispatch, even without mention."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    channel._loop = asyncio.get_running_loop()

    data = _make_sdk_event(
        text="hello",
        chat_type="p2p",
        mentions=[],
    )
    channel._on_message(data)
    await asyncio.sleep(0.05)

    assert len(received) == 1


async def test_on_message_mention_stripped_from_text(channel):
    """Bot's mention tag should be stripped from the text."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    channel._loop = asyncio.get_running_loop()

    mention = _make_mention(open_id="bot_open_id_123", key="@_user_1")
    data = _make_sdk_event(
        text="@_user_1 summarize this",
        chat_type="group",
        mentions=[mention],
    )
    channel._on_message(data)
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].text == "summarize this"


# ---------------------------------------------------------------------------
# Image message tests
# ---------------------------------------------------------------------------


async def test_on_message_image_dispatches(channel):
    """Image message should dispatch with images populated."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    channel._loop = asyncio.get_running_loop()

    # Mock image download
    mock_file = MagicMock()
    mock_file.read.return_value = b"\x89PNG\r\n\x1a\nfakeimage"
    mock_response = MagicMock()
    mock_response.success.return_value = True
    mock_response.file = mock_file
    channel._api_client.im.v1.message_resource.get.return_value = mock_response

    data = _make_sdk_event(message_type="image")
    channel._on_message(data)
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert len(received[0].images) == 1
    assert received[0].images[0].mime_type == "image/png"
    assert received[0].images[0].data == b"\x89PNG\r\n\x1a\nfakeimage"
    assert received[0].text == ""


async def test_on_message_image_download_failure(channel):
    """Image download failure should drop the message."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    channel._loop = asyncio.get_running_loop()

    # Mock failed download
    mock_response = MagicMock()
    mock_response.success.return_value = False
    mock_response.code = 99999
    mock_response.msg = "not found"
    channel._api_client.im.v1.message_resource.get.return_value = mock_response

    data = _make_sdk_event(message_type="image")
    channel._on_message(data)
    await asyncio.sleep(0.05)

    assert len(received) == 0


# ---------------------------------------------------------------------------
# send_message tests
# ---------------------------------------------------------------------------


async def test_send_message_calls_api(channel):
    """send_message should call the sync _send_sync via to_thread."""
    channel._send_sync = MagicMock()

    msg = OutgoingMessage(conversation_id="oc_1", text="hi")
    with patch(
        "ouro.interfaces.bot.channel.lark.asyncio.to_thread", new_callable=AsyncMock
    ) as mock_to_thread:
        await channel.send_message(msg)
        mock_to_thread.assert_called_once_with(channel._send_sync, msg)


# ---------------------------------------------------------------------------
# start / stop lifecycle
# ---------------------------------------------------------------------------


async def test_start_spawns_thread(channel, _mock_lark):
    """start() should create a daemon thread running _run_ws."""
    _, mock_lark = _mock_lark

    cb = AsyncMock()
    with (
        patch("ouro.interfaces.bot.channel.lark.threading.Thread") as MockThread,
        patch("ouro.interfaces.bot.channel.lark.asyncio.to_thread", new_callable=AsyncMock),
    ):
        mock_thread_instance = MagicMock()
        MockThread.return_value = mock_thread_instance

        await channel.start(cb)

        MockThread.assert_called_once()
        call_kwargs = MockThread.call_args[1]
        assert call_kwargs["daemon"] is True
        assert call_kwargs["target"] == channel._run_ws
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


# ---------------------------------------------------------------------------
# File message tests
# ---------------------------------------------------------------------------


async def test_on_message_file_dispatches(channel):
    """File message type should dispatch with files populated."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    channel._loop = asyncio.get_running_loop()

    # Mock file download
    mock_file = MagicMock()
    mock_file.read.return_value = b"%PDF-1.4 fake content"
    mock_response = MagicMock()
    mock_response.success.return_value = True
    mock_response.file = mock_file
    channel._api_client.im.v1.message_resource.get.return_value = mock_response

    data = _make_sdk_event(
        message_type="file",
        content=json.dumps({"file_key": "fk_123", "file_name": "report.pdf"}),
    )
    channel._on_message(data)
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert len(received[0].files) == 1
    assert received[0].files[0].filename == "report.pdf"
    assert received[0].files[0].mime_type == "application/pdf"
    assert received[0].files[0].data == b"%PDF-1.4 fake content"
    assert received[0].text == ""


async def test_on_message_file_download_failure(channel):
    """Failed file download should drop the message."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    channel._loop = asyncio.get_running_loop()

    mock_response = MagicMock()
    mock_response.success.return_value = False
    mock_response.code = 99999
    mock_response.msg = "not found"
    channel._api_client.im.v1.message_resource.get.return_value = mock_response

    data = _make_sdk_event(
        message_type="file",
        content=json.dumps({"file_key": "fk_bad", "file_name": "missing.pdf"}),
    )
    channel._on_message(data)
    await asyncio.sleep(0.05)

    assert len(received) == 0


# ---------------------------------------------------------------------------
# send_file tests
# ---------------------------------------------------------------------------


async def test_send_file_image(channel):
    """send_file with image MIME delegates to _upload_and_send_image."""
    channel._upload_and_send_image = MagicMock(return_value=True)

    with patch(
        "ouro.interfaces.bot.channel.lark.asyncio.to_thread", new_callable=AsyncMock
    ) as mock_thread:
        mock_thread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\nfakeimage")
            f.flush()
            path = f.name

        try:
            result = await channel.send_file(
                conversation_id="oc_1",
                file_path=path,
                mime_type="image/png",
            )
            assert result is True
            channel._upload_and_send_image.assert_called_once()
            call_args = channel._upload_and_send_image.call_args[0]
            assert call_args[0] == "oc_1"  # conversation_id
        finally:
            import os

            os.unlink(path)


async def test_send_file_document(channel):
    """send_file with non-image MIME delegates to _upload_and_send_file."""
    channel._upload_and_send_file = MagicMock(return_value=True)

    with patch(
        "ouro.interfaces.bot.channel.lark.asyncio.to_thread", new_callable=AsyncMock
    ) as mock_thread:
        mock_thread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 fake")
            f.flush()
            path = f.name

        try:
            result = await channel.send_file(
                conversation_id="oc_1",
                file_path=path,
                mime_type="application/pdf",
            )
            assert result is True
            channel._upload_and_send_file.assert_called_once()
        finally:
            import os

            os.unlink(path)


# ---------------------------------------------------------------------------
# Reaction tests
# ---------------------------------------------------------------------------


async def test_add_reaction_calls_api(channel):
    """add_reaction calls message_reaction.create and returns reaction_id."""
    mock_response = MagicMock()
    mock_response.success.return_value = True
    mock_response.data = MagicMock()
    mock_response.data.reaction_id = "react_123"
    channel._api_client.im.v1.message_reaction.create.return_value = mock_response

    with patch(
        "ouro.interfaces.bot.channel.lark.asyncio.to_thread", new_callable=AsyncMock
    ) as mock_thread:
        mock_thread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        result = await channel.add_reaction("oc_1", "msg_001", "eyes")

    assert result == "react_123"
    channel._api_client.im.v1.message_reaction.create.assert_called_once()


async def test_remove_reaction_calls_api(channel):
    """remove_reaction calls message_reaction.delete with correct params."""
    mock_response = MagicMock()
    mock_response.success.return_value = True
    channel._api_client.im.v1.message_reaction.delete.return_value = mock_response

    with patch(
        "ouro.interfaces.bot.channel.lark.asyncio.to_thread", new_callable=AsyncMock
    ) as mock_thread:
        mock_thread.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
        await channel.remove_reaction("oc_1", "msg_001", "eyes", reaction_id="react_123")

    channel._api_client.im.v1.message_reaction.delete.assert_called_once()


async def test_remove_reaction_skips_without_reaction_id(channel):
    """remove_reaction with no reaction_id should be a no-op."""
    with patch(
        "ouro.interfaces.bot.channel.lark.asyncio.to_thread", new_callable=AsyncMock
    ) as mock_thread:
        await channel.remove_reaction("oc_1", "msg_001", "eyes", reaction_id=None)

    mock_thread.assert_not_called()


async def test_platform_message_id_populated(channel):
    """platform_message_id should be set to message_id from the Lark event."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    channel._loop = asyncio.get_running_loop()

    data = _make_sdk_event(text="hello", message_id="lark_msg_001")
    channel._on_message(data)
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].platform_message_id == "lark_msg_001"
