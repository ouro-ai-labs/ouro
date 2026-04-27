"""WeChat channel implementation using weixin-bot-sdk.

Uses ``weixin_bot.WeixinBot`` which provides a long-polling loop via
``bot.run()``.  Since ``run()`` is blocking (it starts its own asyncio
event loop internally), we run it in a daemon thread and bridge messages
back to the main event loop with ``asyncio.run_coroutine_threadsafe()``.

For outgoing messages we schedule coroutines on the bot's internal event
loop so ``bot.send()`` executes in the correct context.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from ouro.interfaces.bot.channel.base import IncomingMessage, OutgoingMessage

if TYPE_CHECKING:
    from ouro.interfaces.bot.channel.base import MessageCallback


logger = logging.getLogger(__name__)

# Maximum number of message IDs to keep for deduplication.
_DEDUP_MAX_SIZE = 2000


class WeChatChannel:
    """WeChat channel backed by weixin-bot-sdk (long polling)."""

    name: str = "wechat"

    def __init__(self) -> None:
        self._callback: MessageCallback | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._bot_loop: asyncio.AbstractEventLoop | None = None
        self._bot: Any = None  # weixin_bot.WeixinBot instance
        self._thread: threading.Thread | None = None

        # Bounded dedup set: OrderedDict used as an ordered set.
        self._seen: OrderedDict[str, None] = OrderedDict()

    # ------------------------------------------------------------------
    # Channel protocol
    # ------------------------------------------------------------------

    async def start(self, message_callback: MessageCallback) -> None:
        """Login via QR code, register handler, and start polling in a daemon thread."""
        from weixin_bot import WeixinBot

        self._callback = message_callback
        self._main_loop = asyncio.get_running_loop()
        self._bot = WeixinBot()

        # Login is synchronous (shows QR code in terminal, waits for scan).
        # Credentials are cached at ~/.weixin-bot/credentials.json for
        # subsequent runs.
        logger.info("WeChat: initiating login (scan QR code if prompted)…")
        await asyncio.to_thread(self._bot.login)
        logger.info("WeChat: login successful")

        # Register the message handler.  The SDK calls this from inside its
        # own event loop (started by ``bot.run()``).
        @self._bot.on_message
        async def _handle(msg: Any) -> None:
            await self._on_message(msg)

        # Run the bot's polling loop in a daemon thread.  ``bot.run()``
        # creates its own asyncio event loop internally, so we capture a
        # reference to it so we can schedule ``bot.send()`` calls from the
        # main loop later.
        self._thread = threading.Thread(
            target=self._run_bot,
            daemon=True,
            name="wechat-poll",
        )
        self._thread.start()
        logger.info("WeChat channel started")

    async def stop(self) -> None:
        """Shut down the WeChat bot."""
        if self._bot is not None:
            try:
                self._bot.stop()
            except Exception:
                logger.debug("Error stopping WeChat bot", exc_info=True)
        self._bot = None
        self._callback = None
        self._main_loop = None
        self._bot_loop = None
        logger.info("WeChat channel stopped")

    async def send_message(self, message: OutgoingMessage) -> None:
        """Send a text message to a WeChat user.

        ``message.conversation_id`` maps to the WeChat ``user_id`` (WeChat
        conversations are 1:1 with users in the bot SDK).
        """
        bot = self._bot
        if bot is None:
            logger.error("Cannot send WeChat message: bot not initialised")
            return

        user_id = message.conversation_id
        try:
            # bot.send() is async and must run in the bot's own event loop.
            if self._bot_loop is not None and self._bot_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    bot.send(user_id, message.text),
                    self._bot_loop,
                )
                # Wait (in a thread) so we don't block the main loop.
                await asyncio.to_thread(future.result, 30)
            else:
                # Fallback: try running directly (if called from bot's loop).
                await bot.send(user_id, message.text)
        except Exception:
            logger.exception("Failed to send WeChat message to %s", user_id)

    async def send_file(
        self,
        conversation_id: str,
        file_path: str | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        mime_type: str | None = None,
    ) -> bool:
        """File sending is not supported via weixin-bot-sdk."""
        logger.debug("WeChat send_file not supported via weixin-bot-sdk")
        return False

    async def add_reaction(self, conversation_id: str, message_id: str, emoji: str) -> str | None:
        """WeChat does not support message reactions — no-op."""
        return None

    async def remove_reaction(
        self,
        conversation_id: str,
        message_id: str,
        emoji: str,
        reaction_id: str | None = None,
    ) -> None:
        """WeChat does not support message reactions — no-op."""

    async def send_typing(self, conversation_id: str) -> None:
        """Show 'typing…' to the WeChat user via the bot SDK.

        The SDK caches a ``context_token`` per user when a message is received,
        so this is only meaningful after at least one incoming message from the
        target user. Errors are swallowed — typing is a UX hint, not
        load-bearing.
        """
        await self._run_on_bot_loop("send_typing", conversation_id)

    async def stop_typing(self, conversation_id: str) -> None:
        """Clear the 'typing…' indicator for the WeChat user."""
        await self._run_on_bot_loop("stop_typing", conversation_id)

    async def _run_on_bot_loop(self, method: str, user_id: str) -> None:
        """Invoke ``bot.<method>(user_id)`` on the SDK's own event loop."""
        bot = self._bot
        if bot is None:
            return
        fn = getattr(bot, method, None)
        if fn is None:
            return
        try:
            if self._bot_loop is not None and self._bot_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(fn(user_id), self._bot_loop)
                await asyncio.to_thread(future.result, 15)
            else:
                await fn(user_id)
        except Exception:
            logger.debug("WeChat %s failed for %s", method, user_id, exc_info=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_bot(self) -> None:
        """Thread target: run the SDK's blocking polling loop.

        The SDK's ``bot.run()`` creates its own asyncio event loop.  We
        capture a reference to it so that ``send_message()`` can schedule
        coroutines there from the main thread.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._bot_loop = loop

        try:
            # The SDK exposes an internal async entry-point we can drive
            # ourselves so we control the event loop.  If that private API
            # isn't available, fall back to the public ``run()`` which
            # creates its own loop (in that case ``_bot_loop`` will already
            # be set but unused for sending — we'll fall through to the
            # ``await bot.send()`` path in ``send_message``).
            run_coro = getattr(self._bot, "_run_async", None)
            if run_coro is not None:
                loop.run_until_complete(run_coro())
            else:
                # ``run()`` manages its own loop — just call it directly.
                # This replaces the loop we just created, so clear our ref.
                self._bot_loop = None
                self._bot.run()
        except Exception:
            logger.exception("WeChat bot polling loop exited unexpectedly")
        finally:
            if not loop.is_closed():
                loop.close()

    async def _on_message(self, msg: Any) -> None:
        """Handle an incoming WeChat message.

        This runs inside the bot SDK's own event loop / thread.  We convert
        the message to an ``IncomingMessage`` and dispatch it to ouro's main
        event loop via ``run_coroutine_threadsafe``.
        """
        if self._callback is None or self._main_loop is None:
            return

        msg_type: str = getattr(msg, "type", "text") or "text"
        text: str = getattr(msg, "text", "") or ""
        user_id: str = getattr(msg, "user_id", "") or ""

        # Only handle text messages for now; images/voice/video/file would
        # require additional SDK support.
        if msg_type != "text" or not text.strip():
            logger.debug("Ignoring non-text or empty WeChat message (type=%s)", msg_type)
            return

        # Build a stable message ID for deduplication.
        platform_msg_id: str = getattr(msg, "id", "") or getattr(msg, "msg_id", "") or ""
        dedup_key = platform_msg_id or f"{user_id}:{hash(text)}:{id(msg)}"
        if self._is_duplicate(dedup_key):
            logger.debug("Duplicate WeChat message %s, skipping", dedup_key)
            return

        incoming = IncomingMessage(
            channel=self.name,
            conversation_id=user_id,  # WeChat 1:1: user_id == conversation
            user_id=user_id,
            text=text.strip(),
            message_id=dedup_key,
            raw={"msg": msg, "type": msg_type},
            platform_message_id=platform_msg_id,
        )

        # Bridge into the main asyncio event loop.
        coro = self._callback(incoming)
        # MessageCallback returns Awaitable[None]; ensure we have a coroutine
        # for run_coroutine_threadsafe.
        if not asyncio.iscoroutine(coro):
            return
        asyncio.run_coroutine_threadsafe(coro, self._main_loop)

    def _is_duplicate(self, msg_id: str) -> bool:
        """Check and record a message ID for deduplication."""
        if not msg_id:
            return False
        if msg_id in self._seen:
            return True
        self._seen[msg_id] = None
        # Evict oldest entries when the dict exceeds the cap.
        while len(self._seen) > _DEDUP_MAX_SIZE:
            self._seen.popitem(last=False)
        return False
