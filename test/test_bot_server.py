"""Tests for the bot server (long-connection architecture)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ouro.interfaces.bot.channel.base import IncomingMessage, OutgoingMessage
from ouro.interfaces.bot.server import BotServer
from ouro.interfaces.bot.session_router import SessionRouter

aiohttp = pytest.importorskip("aiohttp")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

# Short debounce for tests so batches process quickly.
_TEST_DEBOUNCE = 0.05

# ---------------------------------------------------------------------------
# FakeChannel — satisfies the Channel protocol with start/stop
# ---------------------------------------------------------------------------


class FakeChannel:
    """A minimal long-connection channel for testing."""

    name = "test"

    def __init__(self):
        self.sent_messages: list[OutgoingMessage] = []
        self.sent_files: list[dict] = []
        self.reactions_added: list[tuple[str, str, str]] = []  # (conv_id, msg_id, emoji)
        self.reactions_removed: list[tuple[str, str, str, str | None]] = []
        self.typing_starts: list[str] = []
        self.typing_stops: list[str] = []
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

    async def send_file(
        self,
        conversation_id: str,
        file_path: str | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        mime_type: str | None = None,
    ) -> bool:
        self.sent_files.append(
            {
                "conversation_id": conversation_id,
                "file_path": file_path,
                "file_bytes": file_bytes,
                "filename": filename,
                "mime_type": mime_type,
            }
        )
        return True

    async def add_reaction(self, conversation_id: str, message_id: str, emoji: str) -> str | None:
        self.reactions_added.append((conversation_id, message_id, emoji))
        return f"reaction_{emoji}"

    async def remove_reaction(
        self,
        conversation_id: str,
        message_id: str,
        emoji: str,
        reaction_id: str | None = None,
    ) -> None:
        self.reactions_removed.append((conversation_id, message_id, emoji, reaction_id))

    async def send_typing(self, conversation_id: str) -> None:
        self.typing_starts.append(conversation_id)

    async def stop_typing(self, conversation_id: str) -> None:
        self.typing_stops.append(conversation_id)

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
    server = BotServer(
        session_router=mock_router,
        channels=[fake_channel],
        debounce_seconds=_TEST_DEBOUNCE,
    )
    yield server
    for q in server._queues.values():
        q.shutdown()
    server._queues.clear()


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
# _process_message (enqueue path)
# ---------------------------------------------------------------------------


async def test_process_message_sends_ack_and_result(bot_server, fake_channel, mock_router):
    """Test the background message processing flow via queue."""
    msg = IncomingMessage(
        channel="test",
        conversation_id="conv_1",
        user_id="user_1",
        text="What is 2+2?",
        message_id="msg_1",
        platform_message_id="ts_1",
    )

    await bot_server._process_message(fake_channel, msg)
    # Wait for debounce + processing
    await asyncio.sleep(_TEST_DEBOUNCE + 0.15)

    # Should have sent 1 message (agent result only)
    assert len(fake_channel.sent_messages) == 1
    assert fake_channel.sent_messages[0].text == "Agent response"
    assert fake_channel.sent_messages[0].conversation_id == "conv_1"

    # Reactions: processing emoji added then removed, done emoji added
    assert ("conv_1", "ts_1", "eyes") in fake_channel.reactions_added
    assert ("conv_1", "ts_1", "white_check_mark") in fake_channel.reactions_added
    assert any(r[:3] == ("conv_1", "ts_1", "eyes") for r in fake_channel.reactions_removed)


async def test_process_message_error_sends_error_message(bot_server, fake_channel, mock_router):
    """When agent.run() fails, an error message is sent to the user."""
    agent = await mock_router.get_or_create_agent("test", "conv_err")
    agent.run = AsyncMock(side_effect=RuntimeError("LLM timeout"))

    msg = IncomingMessage(
        channel="test",
        conversation_id="conv_err",
        user_id="user_1",
        text="Do something",
        message_id="msg_err",
        platform_message_id="ts_err",
    )

    await bot_server._process_message(fake_channel, msg)
    await asyncio.sleep(_TEST_DEBOUNCE + 0.15)

    # Only error message sent
    assert len(fake_channel.sent_messages) == 1
    assert "went wrong" in fake_channel.sent_messages[0].text

    # Processing reaction should have been cleaned up
    assert any(r[:3] == ("conv_err", "ts_err", "eyes") for r in fake_channel.reactions_removed)


async def test_process_message_shows_typing_indicator(bot_server, fake_channel, mock_router):
    """While the agent is running, the channel should receive typing hints."""
    # Force agent.run to take a bit so the typing loop ticks at least once.
    bot_server._TYPING_REFRESH_SECONDS = 0.01
    agent = await mock_router.get_or_create_agent("test", "conv_typing")

    async def slow_run(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        return "done"

    agent.run = AsyncMock(side_effect=slow_run)

    msg = IncomingMessage(
        channel="test",
        conversation_id="conv_typing",
        user_id="user_1",
        text="Do something slow",
        message_id="msg_typing",
        platform_message_id="ts_typing",
    )

    await bot_server._process_message(fake_channel, msg)
    await asyncio.sleep(_TEST_DEBOUNCE + 0.2)

    assert fake_channel.typing_starts, "send_typing should have been called at least once"
    assert all(c == "conv_typing" for c in fake_channel.typing_starts)
    assert fake_channel.typing_stops == ["conv_typing"]


async def test_process_message_stops_typing_on_error(bot_server, fake_channel, mock_router):
    """stop_typing must still run if the agent raises."""
    bot_server._TYPING_REFRESH_SECONDS = 0.01
    agent = await mock_router.get_or_create_agent("test", "conv_fail")
    agent.run = AsyncMock(side_effect=RuntimeError("boom"))

    msg = IncomingMessage(
        channel="test",
        conversation_id="conv_fail",
        user_id="user_1",
        text="Do something",
        message_id="msg_fail",
        platform_message_id="ts_fail",
    )

    await bot_server._process_message(fake_channel, msg)
    await asyncio.sleep(_TEST_DEBOUNCE + 0.1)

    assert fake_channel.typing_stops == ["conv_fail"]


# ---------------------------------------------------------------------------
# Channel lifecycle (start / stop wiring)
# ---------------------------------------------------------------------------


async def test_channel_start_called_with_callback(fake_channel, mock_router):
    """start() should call channel.start(callback) and register a callback."""
    server = BotServer(
        session_router=mock_router, channels=[fake_channel], debounce_seconds=_TEST_DEBOUNCE
    )

    # We can't call server.start() (it blocks), so test _make_callback + manual start.
    cb = server._make_callback(fake_channel)
    await fake_channel.start(cb)

    assert fake_channel._started is True
    assert fake_channel._callback is not None
    for q in server._queues.values():
        q.shutdown()
    server._queues.clear()


async def test_callback_triggers_process_message(fake_channel, mock_router):
    """Injecting a message through the channel callback triggers processing."""
    server = BotServer(
        session_router=mock_router, channels=[fake_channel], debounce_seconds=_TEST_DEBOUNCE
    )
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

    # The callback creates a task + debounce; give it time to process.
    await asyncio.sleep(_TEST_DEBOUNCE + 0.2)

    assert len(fake_channel.sent_messages) >= 1
    for q in server._queues.values():
        q.shutdown()
    server._queues.clear()


# ---------------------------------------------------------------------------
# _build_channels
# ---------------------------------------------------------------------------


def test_build_channels_lark():
    """_build_channels creates Lark channel when configured and SDK available."""
    mock_lark_channel = MagicMock()
    mock_lark_channel.return_value.name = "lark"
    mock_lark_mod = MagicMock(LarkChannel=mock_lark_channel)

    with (
        patch("bot.server.Config") as mock_config,
        patch.dict("sys.modules", {"bot.channel.lark": mock_lark_mod}),
    ):
        mock_config.LARK_APP_ID = "test_id"
        mock_config.LARK_APP_SECRET = "test_secret"
        mock_config.SLACK_BOT_TOKEN = ""
        mock_config.SLACK_APP_TOKEN = ""
        mock_config.WECHAT_ENABLED = False

        from ouro.interfaces.bot.server import _build_channels

        channels = _build_channels()
        assert len(channels) == 1


def test_build_channels_empty():
    """_build_channels returns empty when nothing configured."""
    with patch("bot.server.Config") as mock_config:
        mock_config.LARK_APP_ID = ""
        mock_config.LARK_APP_SECRET = ""
        mock_config.SLACK_BOT_TOKEN = ""
        mock_config.SLACK_APP_TOKEN = ""
        mock_config.WECHAT_ENABLED = False

        from ouro.interfaces.bot.server import _build_channels

        channels = _build_channels()
        assert len(channels) == 0


# ---------------------------------------------------------------------------
# Slash command tests
# ---------------------------------------------------------------------------


def _make_msg(
    text: str, conv: str = "conv_cmd", platform_message_id: str = "platform_msg_cmd"
) -> IncomingMessage:
    """Helper: build an IncomingMessage with the given text."""
    return IncomingMessage(
        channel="test",
        conversation_id=conv,
        user_id="user_1",
        text=text,
        message_id="msg_cmd",
        platform_message_id=platform_message_id,
    )


async def test_command_new_resets_session(bot_server, fake_channel, mock_router):
    """'/new' destroys the current session and replies with confirmation."""
    # Create a session first
    await mock_router.get_or_create_agent("test", "conv_cmd")
    assert mock_router.active_session_count == 1

    await bot_server._process_message(fake_channel, _make_msg("/new"))

    assert mock_router.active_session_count == 0
    assert len(fake_channel.sent_messages) == 1
    assert "Session reset" in fake_channel.sent_messages[0].text


async def test_command_reset_alias(bot_server, fake_channel, mock_router):
    """'/reset' works the same as '/new'."""
    await mock_router.get_or_create_agent("test", "conv_cmd")

    await bot_server._process_message(fake_channel, _make_msg("/reset"))

    assert mock_router.active_session_count == 0
    assert "Session reset" in fake_channel.sent_messages[0].text


async def test_command_compact(bot_server, fake_channel, mock_router):
    """'/compact' calls agent.memory.compress() and reports savings."""
    mock_result = MagicMock()
    mock_result.original_message_count = 20
    mock_result.token_savings = 1500
    mock_result.savings_percentage = 45.0

    agent = await mock_router.get_or_create_agent("test", "conv_cmd")
    agent.memory.compress = AsyncMock(return_value=mock_result)

    await bot_server._process_message(fake_channel, _make_msg("/compact"))

    agent.memory.compress.assert_awaited_once()
    assert len(fake_channel.sent_messages) == 1
    reply = fake_channel.sent_messages[0].text
    assert "20 messages" in reply
    assert "1500 tokens" in reply
    assert "45%" in reply


async def test_command_compact_nothing_to_compress(bot_server, fake_channel, mock_router):
    """'/compact' with nothing to compress returns appropriate message."""
    agent = await mock_router.get_or_create_agent("test", "conv_cmd")
    agent.memory.compress = AsyncMock(return_value=None)

    await bot_server._process_message(fake_channel, _make_msg("/compact"))

    assert "Nothing to compress" in fake_channel.sent_messages[0].text


async def test_command_status(bot_server, fake_channel, mock_router):
    """'/status' returns session statistics."""
    agent = await mock_router.get_or_create_agent("test", "conv_cmd")
    agent.memory.get_stats.return_value = {
        "current_tokens": 5000,
        "total_input_tokens": 12000,
        "total_output_tokens": 3000,
        "compression_count": 1,
        "short_term_count": 15,
    }

    await bot_server._process_message(fake_channel, _make_msg("/status"))

    assert len(fake_channel.sent_messages) == 1
    reply = fake_channel.sent_messages[0].text
    assert "Messages: 15" in reply
    assert "Context tokens: 5000" in reply
    assert "Session age:" in reply


async def test_command_status_no_session(bot_server, fake_channel):
    """'/status' when no session exists returns helpful message."""
    await bot_server._process_message(fake_channel, _make_msg("/status"))

    assert len(fake_channel.sent_messages) == 1
    assert "No active session" in fake_channel.sent_messages[0].text


async def test_command_help(bot_server, fake_channel):
    """'/help' lists available commands."""
    await bot_server._process_message(fake_channel, _make_msg("/help"))

    assert len(fake_channel.sent_messages) == 1
    reply = fake_channel.sent_messages[0].text
    assert "/new" in reply
    assert "/compact" in reply
    assert "/status" in reply
    assert "/help" in reply


async def test_non_command_passes_through(bot_server, fake_channel, mock_router):
    """A regular message (no / prefix) goes to agent.run() via the queue."""
    await bot_server._process_message(fake_channel, _make_msg("hello world"))
    await asyncio.sleep(_TEST_DEBOUNCE + 0.15)

    # Should see only agent response (ack is via reaction, not text)
    assert len(fake_channel.sent_messages) == 1
    assert fake_channel.sent_messages[0].text == "Agent response"


async def test_unknown_command_passes_through(bot_server, fake_channel, mock_router):
    """An unknown /command is forwarded to agent.run() as a regular message."""
    await bot_server._process_message(fake_channel, _make_msg("/unknown_cmd"))
    await asyncio.sleep(_TEST_DEBOUNCE + 0.15)

    # Should see only agent response (ack is via reaction)
    assert len(fake_channel.sent_messages) == 1
    assert fake_channel.sent_messages[0].text == "Agent response"


async def test_command_with_extra_args(bot_server, fake_channel, mock_router):
    """'/new some_arg' still parses as /new command."""
    await mock_router.get_or_create_agent("test", "conv_cmd")

    await bot_server._process_message(fake_channel, _make_msg("/new some extra text"))

    assert "Session reset" in fake_channel.sent_messages[0].text


async def test_command_case_insensitive(bot_server, fake_channel, mock_router):
    """'/NEW' is treated as /new."""
    await mock_router.get_or_create_agent("test", "conv_cmd")

    await bot_server._process_message(fake_channel, _make_msg("/NEW"))

    assert "Session reset" in fake_channel.sent_messages[0].text


# ---------------------------------------------------------------------------
# File attachment processing tests
# ---------------------------------------------------------------------------


async def test_process_message_with_file_augments_text(bot_server, fake_channel, mock_router):
    """Incoming file attachments are saved to disk and text is augmented."""
    from ouro.interfaces.bot.channel.base import FileAttachment

    msg = IncomingMessage(
        channel="test",
        conversation_id="conv_f",
        user_id="user_1",
        text="Here is a file",
        message_id="msg_f",
        files=[FileAttachment(data=b"hello", filename="test.txt", mime_type="text/plain")],
    )

    agent = await mock_router.get_or_create_agent("test", "conv_f")

    await bot_server._process_message(fake_channel, msg)
    await asyncio.sleep(_TEST_DEBOUNCE + 0.15)

    # agent.run should have been called with augmented text
    call_args = agent.run.call_args
    task_text = call_args[0][0]
    assert "Here is a file" in task_text
    assert "[Attached file: test.txt (text/plain) saved at:" in task_text

    # The temp dir should have been cleaned up
    import re

    m = re.search(r"saved at: (/[^\]]+)", task_text)
    assert m is not None
    import os

    assert not os.path.exists(m.group(1))


async def test_send_file_context_lifecycle(bot_server, fake_channel, mock_router):
    """SendFileContext is set before agent.run() and cleared after."""
    from ouro.capabilities.tools.builtins.send_file_tool import SendFileContext

    agent = await mock_router.get_or_create_agent("test", "conv_ctx")
    ctx = SendFileContext()
    agent._send_file_ctx = ctx

    msg = IncomingMessage(
        channel="test",
        conversation_id="conv_ctx",
        user_id="user_1",
        text="hi",
        message_id="msg_ctx",
    )

    await bot_server._process_message(fake_channel, msg)
    await asyncio.sleep(_TEST_DEBOUNCE + 0.15)

    # After processing, the context should be cleared
    assert ctx._send_fn is None


# ---------------------------------------------------------------------------
# Reaction acknowledgment tests
# ---------------------------------------------------------------------------


async def test_no_platform_id_skips_reactions(bot_server, fake_channel, mock_router):
    """When platform_message_id is empty, no reactions are added."""
    msg = _make_msg("hello world", platform_message_id="")

    await bot_server._process_message(fake_channel, msg)
    await asyncio.sleep(_TEST_DEBOUNCE + 0.15)

    assert len(fake_channel.reactions_added) == 0
    assert len(fake_channel.reactions_removed) == 0
    # Agent response should still be sent
    assert len(fake_channel.sent_messages) == 1
    assert fake_channel.sent_messages[0].text == "Agent response"


async def test_reaction_failure_does_not_block(bot_server, fake_channel, mock_router):
    """add_reaction raising an exception should not block message processing."""

    async def _failing_add(conv_id, msg_id, emoji):
        raise RuntimeError("API down")

    fake_channel.add_reaction = _failing_add  # type: ignore[assignment]

    msg = _make_msg("hello world")

    await bot_server._process_message(fake_channel, msg)
    await asyncio.sleep(_TEST_DEBOUNCE + 0.15)

    # Processing should complete normally — agent response sent
    assert len(fake_channel.sent_messages) == 1
    assert fake_channel.sent_messages[0].text == "Agent response"


# ---------------------------------------------------------------------------
# Message queue batch integration tests
# ---------------------------------------------------------------------------


async def test_rapid_messages_coalesced_into_single_agent_call(fake_channel, mock_router):
    """Multiple rapid messages should be coalesced into a single agent.run() call."""
    server = BotServer(
        session_router=mock_router,
        channels=[fake_channel],
        debounce_seconds=0.1,
    )
    try:
        for i in range(3):
            msg = IncomingMessage(
                channel="test",
                conversation_id="conv_batch",
                user_id="user_1",
                text=f"message {i}",
                message_id=f"msg_{i}",
                platform_message_id=f"ts_{i}",
            )
            await server._process_message(fake_channel, msg)

        # Wait for debounce + processing
        await asyncio.sleep(0.4)

        # Should have exactly one agent response (batched)
        assert len(fake_channel.sent_messages) == 1
        assert fake_channel.sent_messages[0].text == "Agent response"

        # agent.run should have been called once with combined text
        agent = await mock_router.get_or_create_agent("test", "conv_batch")
        assert agent.run.await_count == 1
        call_text = agent.run.call_args[0][0]
        assert "message 0" in call_text
        assert "message 1" in call_text
        assert "message 2" in call_text

        # All 3 messages got 👀 reaction immediately
        eyes_reactions = [r for r in fake_channel.reactions_added if r[2] == "eyes"]
        assert len(eyes_reactions) == 3

        # All 3 messages got ✅ after processing
        done_reactions = [r for r in fake_channel.reactions_added if r[2] == "white_check_mark"]
        assert len(done_reactions) == 3
    finally:
        for q in server._queues.values():
            q.shutdown()
        server._queues.clear()


async def test_slash_commands_bypass_queue(fake_channel, mock_router):
    """Slash commands are handled immediately without going through the queue."""
    server = BotServer(
        session_router=mock_router,
        channels=[fake_channel],
        debounce_seconds=5.0,  # Long debounce — commands should still be instant
    )
    try:
        await mock_router.get_or_create_agent("test", "conv_cmd")

        msg = _make_msg("/help")
        await server._process_message(fake_channel, msg)

        # No debounce wait needed — commands are synchronous
        assert len(fake_channel.sent_messages) == 1
        assert "/new" in fake_channel.sent_messages[0].text
    finally:
        for q in server._queues.values():
            q.shutdown()
        server._queues.clear()


async def test_batch_error_cleans_up_all_reactions(fake_channel, mock_router):
    """When agent.run() fails for a batch, all messages get reactions cleaned up."""
    agent = await mock_router.get_or_create_agent("test", "conv_err_batch")
    agent.run = AsyncMock(side_effect=RuntimeError("LLM timeout"))

    server = BotServer(
        session_router=mock_router,
        channels=[fake_channel],
        debounce_seconds=0.05,
    )
    try:
        for i in range(2):
            msg = IncomingMessage(
                channel="test",
                conversation_id="conv_err_batch",
                user_id="user_1",
                text=f"msg {i}",
                message_id=f"msg_{i}",
                platform_message_id=f"ts_{i}",
            )
            await server._process_message(fake_channel, msg)

        await asyncio.sleep(0.3)

        # Both processing reactions should have been cleaned up
        eyes_removed = [r for r in fake_channel.reactions_removed if r[2] == "eyes"]
        assert len(eyes_removed) == 2

        # Error message should be sent
        assert any("went wrong" in m.text for m in fake_channel.sent_messages)
    finally:
        for q in server._queues.values():
            q.shutdown()
        server._queues.clear()
