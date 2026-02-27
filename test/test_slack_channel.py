"""Tests for the Slack Socket Mode channel implementation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.channel.base import IncomingMessage, OutgoingMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_socket_request(
    text: str = "hello",
    channel_id: str = "C123",
    user_id: str = "U456",
    client_msg_id: str = "cmsg_1",
    ts: str = "1234567890.000100",
    event_type: str = "message",
    req_type: str = "events_api",
    bot_id: str | None = None,
    subtype: str | None = None,
    channel_type: str = "im",
    files: list | None = None,
) -> MagicMock:
    """Build a mock SocketModeRequest."""
    event: dict = {
        "type": event_type,
        "text": text,
        "channel": channel_id,
        "user": user_id,
        "ts": ts,
        "channel_type": channel_type,
    }
    if client_msg_id:
        event["client_msg_id"] = client_msg_id
    if bot_id:
        event["bot_id"] = bot_id
    if subtype:
        event["subtype"] = subtype
    if files:
        event["files"] = files

    req = MagicMock()
    req.type = req_type
    req.envelope_id = "env_001"
    req.payload = {"event": event}
    return req


# ---------------------------------------------------------------------------
# Fixture — import SlackChannel with slack_sdk mocked
# ---------------------------------------------------------------------------


@pytest.fixture
def _mock_slack():
    """Patch slack_sdk so SlackChannel can be imported without the real SDK."""
    mock_socket_client_cls = MagicMock()
    mock_socket_client_instance = AsyncMock()
    mock_socket_client_instance.socket_mode_request_listeners = []
    mock_socket_client_cls.return_value = mock_socket_client_instance

    mock_web_client_cls = MagicMock()
    mock_web_client_instance = AsyncMock()
    mock_web_client_cls.return_value = mock_web_client_instance

    mock_request_mod = MagicMock()
    mock_response_mod = MagicMock()
    mock_response_cls = MagicMock()
    mock_response_mod.SocketModeResponse = mock_response_cls

    modules = {
        "slack_sdk": MagicMock(),
        "slack_sdk.socket_mode": MagicMock(),
        "slack_sdk.socket_mode.aiohttp": MagicMock(SocketModeClient=mock_socket_client_cls),
        "slack_sdk.socket_mode.request": mock_request_mod,
        "slack_sdk.socket_mode.response": mock_response_mod,
        "slack_sdk.web": MagicMock(),
        "slack_sdk.web.async_client": MagicMock(AsyncWebClient=mock_web_client_cls),
    }

    with (
        patch.dict("sys.modules", modules),
        patch("config.Config") as mock_config,
    ):
        mock_config.SLACK_BOT_TOKEN = "xoxb-test"
        mock_config.SLACK_APP_TOKEN = "xapp-test"

        import importlib

        import bot.channel.slack as slack_mod

        importlib.reload(slack_mod)
        # Bind the real SocketModeResponse into the reloaded module so ack works.
        slack_mod.SocketModeResponse = mock_response_cls

        yield slack_mod, mock_socket_client_instance, mock_web_client_instance, mock_response_cls


@pytest.fixture
def channel(_mock_slack):
    slack_mod, _, _, _ = _mock_slack
    ch = slack_mod.SlackChannel()
    ch._bot_user_id = "UBOTID"
    return ch


@pytest.fixture
def mock_socket_client(_mock_slack):
    _, client, _, _ = _mock_slack
    return client


@pytest.fixture
def mock_response_cls(_mock_slack):
    _, _, _, resp_cls = _mock_slack
    return resp_cls


# ---------------------------------------------------------------------------
# _on_request handler tests
# ---------------------------------------------------------------------------


async def test_on_request_dispatches_message(channel, mock_response_cls):
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb

    client = AsyncMock()
    req = _make_socket_request(text="hi there", channel_id="C1", user_id="U1", client_msg_id="c1")
    await channel._on_request(client, req)

    # Acked
    client.send_socket_mode_response.assert_called_once()

    assert len(received) == 1
    assert received[0].text == "hi there"
    assert received[0].channel == "slack"
    assert received[0].conversation_id == "C1"
    assert received[0].user_id == "U1"


async def test_on_request_skips_bot_messages(channel):
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb

    client = AsyncMock()
    req = _make_socket_request(bot_id="B123")
    await channel._on_request(client, req)

    assert len(received) == 0


async def test_on_request_skips_subtypes(channel):
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb

    client = AsyncMock()
    req = _make_socket_request(subtype="message_changed")
    await channel._on_request(client, req)

    assert len(received) == 0


async def test_on_request_skips_non_events_api(channel):
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb

    client = AsyncMock()
    req = _make_socket_request(req_type="slash_commands")
    await channel._on_request(client, req)

    assert len(received) == 0


async def test_on_request_skips_non_message_event(channel):
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb

    client = AsyncMock()
    req = _make_socket_request(event_type="app_mention")
    await channel._on_request(client, req)

    assert len(received) == 0


async def test_on_request_skips_empty_text(channel):
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb

    client = AsyncMock()
    req = _make_socket_request(text="   ")
    await channel._on_request(client, req)

    assert len(received) == 0


async def test_on_request_dedup(channel):
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb
    client = AsyncMock()

    req = _make_socket_request(client_msg_id="dup1")
    await channel._on_request(client, req)
    await channel._on_request(client, req)

    assert len(received) == 1


async def test_on_request_always_acks(channel):
    """Even non-message events should be acked."""
    channel._callback = AsyncMock()

    client = AsyncMock()
    req = _make_socket_request(req_type="slash_commands")
    await channel._on_request(client, req)

    client.send_socket_mode_response.assert_called_once()


# ---------------------------------------------------------------------------
# @ Mention filtering tests
# ---------------------------------------------------------------------------


async def test_on_request_channel_mention_dispatches(channel):
    """Channel message with @bot mention should dispatch."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb

    client = AsyncMock()
    req = _make_socket_request(
        text="<@UBOTID> what is this?",
        channel_type="channel",
    )
    await channel._on_request(client, req)

    assert len(received) == 1


async def test_on_request_channel_no_mention_ignored(channel):
    """Channel message without @bot mention should be ignored."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb

    client = AsyncMock()
    req = _make_socket_request(
        text="hey everyone",
        channel_type="channel",
    )
    await channel._on_request(client, req)

    assert len(received) == 0


async def test_on_request_dm_always_dispatches(channel):
    """DM messages should always dispatch, even without mention."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb

    client = AsyncMock()
    req = _make_socket_request(
        text="hello",
        channel_type="im",
    )
    await channel._on_request(client, req)

    assert len(received) == 1


async def test_on_request_mention_stripped(channel):
    """Bot's mention tag should be stripped from the text."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb

    client = AsyncMock()
    req = _make_socket_request(
        text="<@UBOTID> summarize this",
        channel_type="channel",
    )
    await channel._on_request(client, req)

    assert len(received) == 1
    assert received[0].text == "summarize this"


async def test_on_request_image_attachment(channel):
    """Message with image file attachment should populate images."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb

    client = AsyncMock()
    files = [
        {
            "mimetype": "image/png",
            "url_private_download": "https://files.slack.com/img.png",
        }
    ]
    req = _make_socket_request(
        text="look at this image",
        files=files,
    )

    with patch.object(channel, "_download_file", new_callable=AsyncMock) as mock_dl:
        mock_dl.return_value = b"\x89PNGfakedata"
        await channel._on_request(client, req)

    assert len(received) == 1
    assert len(received[0].images) == 1
    assert received[0].images[0].mime_type == "image/png"
    assert received[0].images[0].data == b"\x89PNGfakedata"


async def test_on_request_image_only_no_text(channel):
    """Image-only message (no text) should still dispatch."""
    received: list[IncomingMessage] = []

    async def cb(msg: IncomingMessage) -> None:
        received.append(msg)

    channel._callback = cb

    client = AsyncMock()
    files = [
        {
            "mimetype": "image/jpeg",
            "url_private_download": "https://files.slack.com/photo.jpg",
        }
    ]
    req = _make_socket_request(
        text="",
        files=files,
        subtype="file_share",
    )

    with patch.object(channel, "_download_file", new_callable=AsyncMock) as mock_dl:
        mock_dl.return_value = b"\xff\xd8\xff\xe0fakejpeg"
        await channel._on_request(client, req)

    assert len(received) == 1
    assert received[0].text == ""
    assert len(received[0].images) == 1
    assert received[0].images[0].mime_type == "image/jpeg"


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


async def test_send_message(channel):
    channel._web_client.chat_postMessage = AsyncMock(return_value={"ok": True})

    msg = OutgoingMessage(conversation_id="C1", text="Hello!")
    await channel.send_message(msg)

    channel._web_client.chat_postMessage.assert_called_once_with(channel="C1", text="Hello!")


# ---------------------------------------------------------------------------
# Dedup eviction
# ---------------------------------------------------------------------------


def test_dedup_bounded_size(channel):
    """Dedup dict should not grow beyond _DEDUP_MAX_SIZE."""
    import bot.channel.slack as slack_mod

    original_max = slack_mod._DEDUP_MAX_SIZE
    slack_mod._DEDUP_MAX_SIZE = 5
    try:
        for i in range(10):
            assert not channel._is_duplicate(f"msg_{i}")
        assert len(channel._seen) == 5
    finally:
        slack_mod._DEDUP_MAX_SIZE = original_max


# ---------------------------------------------------------------------------
# start / stop lifecycle
# ---------------------------------------------------------------------------


async def test_start_connects(channel, mock_socket_client):
    channel._socket_client = mock_socket_client
    cb = AsyncMock()

    await channel.start(cb)

    # connect() should have been called
    mock_socket_client.connect.assert_called_once()
    assert channel._callback is cb


async def test_stop_closes(channel, mock_socket_client):
    channel._socket_client = mock_socket_client
    channel._callback = AsyncMock()

    await channel.stop()

    mock_socket_client.close.assert_called_once()
    assert channel._callback is None
