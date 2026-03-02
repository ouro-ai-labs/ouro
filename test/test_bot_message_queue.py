"""Tests for bot message queue: coalescing, debounce, and queue lifecycle."""

from __future__ import annotations

import asyncio

import pytest

from bot.channel.base import IncomingMessage
from bot.message_queue import (
    ConversationQueue,
    coalesce_messages,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(
    text: str = "hello",
    user_id: str = "user_1",
    conv: str = "conv_1",
    channel: str = "test",
    msg_id: str = "",
    platform_msg_id: str = "",
) -> IncomingMessage:
    return IncomingMessage(
        channel=channel,
        conversation_id=conv,
        user_id=user_id,
        text=text,
        message_id=msg_id or f"mid_{id(text)}",
        platform_message_id=platform_msg_id,
    )


# ---------------------------------------------------------------------------
# coalesce_messages — pure function tests
# ---------------------------------------------------------------------------


class TestCoalesceMessages:
    def test_single_message(self):
        result = coalesce_messages([_msg("hi")])
        assert result == "hi"

    def test_multiple_same_user(self):
        msgs = [_msg("first"), _msg("second"), _msg("third")]
        result = coalesce_messages(msgs)
        assert result == "first\n\nsecond\n\nthird"

    def test_multiple_different_users(self):
        msgs = [
            _msg("hello", user_id="alice"),
            _msg("hi there", user_id="bob"),
            _msg("hey!", user_id="alice"),
        ]
        result = coalesce_messages(msgs)
        assert "[alice] hello" in result
        assert "[bob] hi there" in result
        assert "[alice] hey!" in result

    def test_empty_text_omitted(self):
        """Image-only messages (empty text) are handled gracefully."""
        msgs = [_msg(""), _msg("hello")]
        result = coalesce_messages(msgs)
        assert result == "hello"

    def test_all_empty_text(self):
        """All empty-text messages produce empty string."""
        result = coalesce_messages([_msg(""), _msg("  ")])
        assert result == ""

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="empty"):
            coalesce_messages([])

    def test_whitespace_stripped(self):
        result = coalesce_messages([_msg("  hello  "), _msg("  world  ")])
        assert result == "hello\n\nworld"


# ---------------------------------------------------------------------------
# ConversationQueue — async tests
# ---------------------------------------------------------------------------


class TestConversationQueue:
    async def test_single_message_processes_after_debounce(self):
        batches: list[list[IncomingMessage]] = []

        async def callback(batch: list[IncomingMessage]) -> None:
            batches.append(batch)

        q = ConversationQueue("test:conv1", callback, debounce_seconds=0.05, idle_timeout=1.0)
        try:
            await q.enqueue(_msg("hello"))
            await asyncio.sleep(0.2)
            assert len(batches) == 1
            assert batches[0][0].text == "hello"
        finally:
            q.shutdown()

    async def test_rapid_messages_coalesced(self):
        batches: list[list[IncomingMessage]] = []

        async def callback(batch: list[IncomingMessage]) -> None:
            batches.append(batch)

        q = ConversationQueue("test:conv1", callback, debounce_seconds=0.1, idle_timeout=1.0)
        try:
            await q.enqueue(_msg("one"))
            await asyncio.sleep(0.03)
            await q.enqueue(_msg("two"))
            await asyncio.sleep(0.03)
            await q.enqueue(_msg("three"))
            # Wait for debounce to fire
            await asyncio.sleep(0.3)
            assert len(batches) == 1
            assert len(batches[0]) == 3
        finally:
            q.shutdown()

    async def test_max_batch_size_forces_processing(self):
        batches: list[list[IncomingMessage]] = []

        async def callback(batch: list[IncomingMessage]) -> None:
            batches.append(batch)

        q = ConversationQueue(
            "test:conv1",
            callback,
            debounce_seconds=5.0,  # long debounce
            max_batch_size=3,
            idle_timeout=1.0,
        )
        try:
            # Send exactly max_batch_size messages rapidly
            for i in range(3):
                await q.enqueue(_msg(f"msg{i}"))
            # Should process immediately once max_batch_size reached
            await asyncio.sleep(0.2)
            assert len(batches) == 1
            assert len(batches[0]) == 3
        finally:
            q.shutdown()

    async def test_consumer_auto_stops_on_idle(self):
        batches: list[list[IncomingMessage]] = []

        async def callback(batch: list[IncomingMessage]) -> None:
            batches.append(batch)

        q = ConversationQueue("test:conv1", callback, debounce_seconds=0.02, idle_timeout=0.1)
        await q.enqueue(_msg("hi"))
        await asyncio.sleep(0.25)  # debounce + idle timeout
        assert len(batches) == 1

        # Consumer should have stopped
        assert q._task is not None
        assert q._task.done()

    async def test_consumer_restarts_on_new_message(self):
        batches: list[list[IncomingMessage]] = []

        async def callback(batch: list[IncomingMessage]) -> None:
            batches.append(batch)

        q = ConversationQueue("test:conv1", callback, debounce_seconds=0.02, idle_timeout=0.1)
        try:
            await q.enqueue(_msg("first"))
            await asyncio.sleep(0.25)  # let consumer stop
            assert len(batches) == 1

            # New message should restart consumer
            await q.enqueue(_msg("second"))
            await asyncio.sleep(0.15)
            assert len(batches) == 2
        finally:
            q.shutdown()

    async def test_shutdown_cancels_consumer(self):
        async def callback(batch: list[IncomingMessage]) -> None:
            await asyncio.sleep(10)  # would block forever

        q = ConversationQueue("test:conv1", callback, debounce_seconds=0.01, idle_timeout=100)
        await q.enqueue(_msg("hi"))
        await asyncio.sleep(0.05)  # let consumer start

        q.shutdown()
        assert q._task is None

    async def test_sequential_batches(self):
        """Two batches separated by more than debounce time are independent."""
        batches: list[list[IncomingMessage]] = []

        async def callback(batch: list[IncomingMessage]) -> None:
            batches.append(batch)

        q = ConversationQueue("test:conv1", callback, debounce_seconds=0.05, idle_timeout=1.0)
        try:
            await q.enqueue(_msg("batch1"))
            await asyncio.sleep(0.15)
            assert len(batches) == 1

            await q.enqueue(_msg("batch2"))
            await asyncio.sleep(0.15)
            assert len(batches) == 2
            assert batches[0][0].text == "batch1"
            assert batches[1][0].text == "batch2"
        finally:
            q.shutdown()
