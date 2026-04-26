"""Message queue with debounce and intelligent coalescing for bot mode.

Batches rapid-fire messages per conversation into a single agent call,
making the bot feel more like chatting with a human who reads all your
messages before responding.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from ouro.interfaces.bot.channel.base import IncomingMessage

logger = logging.getLogger(__name__)


def coalesce_messages(messages: list[IncomingMessage]) -> str:
    """Merge message texts into a single string.

    - Single user: join texts with blank-line separation.
    - Multi-user (group chat): prefix each with ``[user_id]``.
    - Empty text (image-only messages): omitted.

    Pure and stateless — easy to test.
    """
    if not messages:
        raise ValueError("Cannot coalesce an empty message list")

    users = {m.user_id for m in messages}
    multi_user = len(users) > 1

    parts: list[str] = []
    for msg in messages:
        text = msg.text.strip()
        if not text:
            continue
        if multi_user:
            parts.append(f"[{msg.user_id}] {text}")
        else:
            parts.append(text)

    return "\n\n".join(parts)


class ConversationQueue:
    """Async queue for a single conversation with sliding-window debounce.

    The consumer auto-starts on first ``enqueue()`` and auto-stops after
    ``idle_timeout`` seconds with no messages.
    """

    def __init__(
        self,
        key: str,
        callback: Callable[[list[IncomingMessage]], Awaitable[None]],
        *,
        debounce_seconds: float = 1.5,
        max_batch_size: int = 20,
        idle_timeout: float = 300.0,
    ) -> None:
        self._key = key
        self._callback = callback
        self._debounce = debounce_seconds
        self._max_batch = max_batch_size
        self._idle_timeout = idle_timeout
        self._queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def enqueue(self, msg: IncomingMessage) -> None:
        """Add a message and ensure the consumer is running."""
        await self._queue.put(msg)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._consumer())

    async def _wait_next(self, timeout: float) -> IncomingMessage | None:
        """Wait for a message with timeout, returning ``None`` on expiry."""
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def _consumer(self) -> None:
        """Wait for messages, collect with debounce, invoke callback."""
        try:
            while True:
                first = await self._wait_next(self._idle_timeout)
                if first is None:
                    logger.debug("Queue %s idle, consumer stopping", self._key)
                    return

                batch = [first]
                while len(batch) < self._max_batch:
                    msg = await self._wait_next(self._debounce)
                    if msg is None:
                        break
                    batch.append(msg)

                try:
                    await self._callback(batch)
                except Exception:
                    logger.exception(
                        "Error processing batch for %s (%d msgs)",
                        self._key,
                        len(batch),
                    )
        except asyncio.CancelledError:
            logger.debug("Consumer for %s cancelled", self._key)

    def shutdown(self) -> None:
        """Cancel the consumer task if running."""
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
