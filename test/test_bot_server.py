"""Tests for the bot server (long-connection architecture)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.channel.base import IncomingMessage, OutgoingMessage
from bot.server import BotServer
from bot.session_router import SessionRouter

aiohttp = pytest.importorskip("aiohttp")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

# ---------------------------------------------------------------------------
# FakeChannel — satisfies the Channel protocol with start/stop
# ---------------------------------------------------------------------------


class FakeChannel:
    """A minimal long-connection channel for testing."""

    name = "test"

    def __init__(self):
        self.sent_messages: list[OutgoingMessage] = []
        self._callback = None
        self._started = False
        self._stopped = False

    async def start(self, message_callback) -> None:
        self._callback = message_callback
        self._started = True

    async def stop(self) -> None:
        self._stopped = True
        self._callback = None

    async def send_message(self, message: OutgoingMessage) -> None:
        self.sent_messages.append(message)

    async def inject_message(self, msg: IncomingMessage) -> None:
        """Simulate an incoming message from the IM platform."""
        if self._callback is not None:
            await self._callback(msg)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_channel():
    return FakeChannel()


@pytest.fixture
def mock_router():
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value="Agent response")
    router = SessionRouter(agent_factory=lambda: mock_agent)
    return router


@pytest.fixture
def bot_server(mock_router, fake_channel):
    return BotServer(
        session_router=mock_router,
        channels=[fake_channel],
    )


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


async def test_health_endpoint(bot_server):
    client = TestClient(TestServer(bot_server._app))
    await client.start_server()
    try:
        resp = await client.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert "active_sessions" in data
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# _process_message
# ---------------------------------------------------------------------------


async def test_process_message_sends_ack_and_result(bot_server, fake_channel, mock_router):
    """Test the background message processing flow."""
    msg = IncomingMessage(
        channel="test",
        conversation_id="conv_1",
        user_id="user_1",
        text="What is 2+2?",
        message_id="msg_1",
    )

    await bot_server._process_message(fake_channel, msg)

    # Should have sent 2 messages: ack + result
    assert len(fake_channel.sent_messages) == 2
    assert fake_channel.sent_messages[0].text == "Working on it..."
    assert fake_channel.sent_messages[1].text == "Agent response"
    assert fake_channel.sent_messages[0].conversation_id == "conv_1"


async def test_process_message_error_sends_error_message(bot_server, fake_channel, mock_router):
    """When agent.run() fails, an error message is sent to the user."""
    agent = mock_router.get_or_create_agent("test", "conv_err")
    agent.run = AsyncMock(side_effect=RuntimeError("LLM timeout"))

    msg = IncomingMessage(
        channel="test",
        conversation_id="conv_err",
        user_id="user_1",
        text="Do something",
        message_id="msg_err",
    )

    await bot_server._process_message(fake_channel, msg)

    assert len(fake_channel.sent_messages) == 2
    assert "Working on it..." in fake_channel.sent_messages[0].text
    assert "went wrong" in fake_channel.sent_messages[1].text


# ---------------------------------------------------------------------------
# Channel lifecycle (start / stop wiring)
# ---------------------------------------------------------------------------


async def test_channel_start_called_with_callback(fake_channel, mock_router):
    """start() should call channel.start(callback) and register a callback."""
    server = BotServer(session_router=mock_router, channels=[fake_channel])

    # We can't call server.start() (it blocks), so test _make_callback + manual start.
    cb = server._make_callback(fake_channel)
    await fake_channel.start(cb)

    assert fake_channel._started is True
    assert fake_channel._callback is not None


async def test_callback_triggers_process_message(fake_channel, mock_router):
    """Injecting a message through the channel callback triggers processing."""
    server = BotServer(session_router=mock_router, channels=[fake_channel])
    cb = server._make_callback(fake_channel)
    await fake_channel.start(cb)

    msg = IncomingMessage(
        channel="test",
        conversation_id="conv_1",
        user_id="user_1",
        text="hi",
        message_id="msg_1",
    )
    await fake_channel.inject_message(msg)

    # The callback creates a task; give it a moment to run.
    await asyncio.sleep(0.1)

    assert len(fake_channel.sent_messages) >= 1


# ---------------------------------------------------------------------------
# _build_channels
# ---------------------------------------------------------------------------


def test_build_channels_feishu():
    """_build_channels creates Feishu channel when configured and SDK available."""
    mock_feishu_channel = MagicMock()
    mock_feishu_channel.return_value.name = "feishu"
    mock_feishu_mod = MagicMock(FeishuChannel=mock_feishu_channel)

    with (
        patch("bot.server.Config") as mock_config,
        patch.dict("sys.modules", {"bot.channel.feishu": mock_feishu_mod}),
    ):
        mock_config.FEISHU_APP_ID = "test_id"
        mock_config.FEISHU_APP_SECRET = "test_secret"
        mock_config.SLACK_BOT_TOKEN = ""
        mock_config.SLACK_APP_TOKEN = ""

        from bot.server import _build_channels

        channels = _build_channels()
        assert len(channels) == 1


def test_build_channels_empty():
    """_build_channels returns empty when nothing configured."""
    with patch("bot.server.Config") as mock_config:
        mock_config.FEISHU_APP_ID = ""
        mock_config.FEISHU_APP_SECRET = ""
        mock_config.SLACK_BOT_TOKEN = ""
        mock_config.SLACK_APP_TOKEN = ""

        from bot.server import _build_channels

        channels = _build_channels()
        assert len(channels) == 0
