"""Lark (Feishu) WebSocket channel implementation for bot mode.

Uses ``lark-oapi`` SDK long connection (WebSocket).  The SDK's
``lark.ws.Client.start()`` is **blocking**, so we run it in a daemon thread
and bridge callbacks into the asyncio event loop with
``run_coroutine_threadsafe``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import TYPE_CHECKING

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    GetMessageResourceRequest,
    P2ImMessageReceiveV1,
)

from bot.channel.base import ImageData, IncomingMessage, OutgoingMessage

if TYPE_CHECKING:
    from bot.channel.base import MessageCallback

from config import Config

logger = logging.getLogger(__name__)


class LarkChannel:
    """Lark channel backed by a WebSocket long connection."""

    name: str = "lark"

    def __init__(self) -> None:
        self._app_id = Config.LARK_APP_ID
        self._app_secret = Config.LARK_APP_SECRET

        self._callback: MessageCallback | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws_client: lark.ws.Client | None = None
        self._thread: threading.Thread | None = None
        self._bot_open_id: str = ""

        # Sync lark client for sending messages.
        self._api_client = (
            lark.Client.builder().app_id(self._app_id).app_secret(self._app_secret).build()
        )

    # ------------------------------------------------------------------
    # Channel protocol
    # ------------------------------------------------------------------

    async def start(self, message_callback: MessageCallback) -> None:
        """Open the WebSocket connection and begin dispatching messages."""
        self._callback = message_callback
        self._loop = asyncio.get_running_loop()

        # Fetch bot's own open_id so we can filter group @mentions.
        await asyncio.to_thread(self._fetch_bot_info)

        # Build the event handler for im.message.receive_v1
        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message)
            .build()
        )

        self._ws_client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.WARNING,
        )

        # lark.ws.Client.start() blocks and internally calls
        # loop.run_until_complete(), so it needs its own event loop.
        self._thread = threading.Thread(
            target=self._run_ws,
            daemon=True,
            name="lark-ws",
        )
        self._thread.start()
        logger.info("Lark WebSocket channel started (bot_open_id=%s)", self._bot_open_id)

    async def stop(self) -> None:
        """Shut down the WebSocket connection."""
        # The SDK doesn't expose a public stop(); the daemon thread will be
        # reaped on process exit.  Clear internal references.
        self._ws_client = None
        self._callback = None
        self._loop = None
        logger.info("Lark WebSocket channel stopped")

    async def send_message(self, message: OutgoingMessage) -> None:
        """Send a text message to a Lark chat (async-safe)."""
        await asyncio.to_thread(self._send_sync, message)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_bot_info(self) -> None:
        """Fetch the bot's own open_id via the Lark bot info API."""
        try:
            from lark_oapi.api.bot.v3 import GetBotInfoRequest

            request = GetBotInfoRequest.builder().build()
            response = self._api_client.bot.v3.bot_info.get(request)
            if response.success() and response.data and response.data.bot:
                self._bot_open_id = response.data.bot.open_id or ""
                logger.info("Fetched bot open_id: %s", self._bot_open_id)
            else:
                logger.warning(
                    "Failed to fetch bot info: code=%s msg=%s",
                    getattr(response, "code", "?"),
                    getattr(response, "msg", "?"),
                )
        except Exception:
            logger.warning(
                "Could not fetch bot info — mention filtering may not work", exc_info=True
            )

    def _run_ws(self) -> None:
        """Thread target: create a fresh event loop for the SDK.

        The lark-oapi SDK captures ``asyncio.get_event_loop()`` into a
        module-level ``loop`` variable at import time and uses it in
        ``start()``.  When we're already inside an asyncio application the
        captured loop is the *running* main-thread loop, so
        ``loop.run_until_complete()`` fails.  We work around this by
        replacing the module-level variable before calling ``start()``.
        """
        import lark_oapi.ws.client as _ws_mod

        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        _ws_mod.loop = new_loop  # patch SDK's module-level loop
        try:
            if self._ws_client is not None:
                self._ws_client.start()
        finally:
            new_loop.close()

    def _on_message(self, data: P2ImMessageReceiveV1) -> None:
        """SDK callback — runs in the SDK/WS thread."""
        if self._callback is None or self._loop is None:
            return

        event = data.event
        if event is None:
            return

        msg_obj = event.message
        sender = event.sender
        if msg_obj is None or sender is None:
            return

        # --- @ mention filtering for group chats ---
        chat_type = getattr(msg_obj, "chat_type", "p2p")
        if chat_type == "group" and self._bot_open_id:
            mentions = getattr(msg_obj, "mentions", None) or []
            bot_mentioned = any(
                getattr(m, "id", None) and getattr(m.id, "open_id", None) == self._bot_open_id
                for m in mentions
            )
            if not bot_mentioned:
                logger.debug("Ignoring group message without bot mention")
                return

        # --- Parse by message type ---
        text = ""
        images: list[ImageData] = []

        if msg_obj.message_type == "text":
            # Parse text content (Lark wraps it in JSON: {"text": "hello"}).
            try:
                content = json.loads(msg_obj.content or "{}")
                text = content.get("text", "")
            except json.JSONDecodeError:
                text = msg_obj.content or ""
        elif msg_obj.message_type == "image":
            try:
                content = json.loads(msg_obj.content or "{}")
                image_key = content.get("image_key", "")
            except json.JSONDecodeError:
                image_key = ""
            if image_key:
                image_bytes = self._download_image(msg_obj.message_id or "", image_key)
                if image_bytes:
                    images.append(ImageData(data=image_bytes, mime_type="image/png"))
                else:
                    logger.warning("Failed to download image, dropping message")
                    return
            else:
                return
        else:
            logger.debug("Ignoring message type: %s", msg_obj.message_type)
            return

        # Strip bot mention placeholder from text in group chats.
        if chat_type == "group" and self._bot_open_id:
            mentions = getattr(msg_obj, "mentions", None) or []
            for m in mentions:
                m_id = getattr(m, "id", None)
                if m_id and getattr(m_id, "open_id", None) == self._bot_open_id:
                    key = getattr(m, "key", None)
                    if key:
                        text = text.replace(key, "").strip()

        if not text.strip() and not images:
            return

        incoming = IncomingMessage(
            channel=self.name,
            conversation_id=msg_obj.chat_id or "",
            user_id=(sender.sender_id.open_id if sender.sender_id else "") or "",
            text=text.strip(),
            message_id=msg_obj.message_id or "",
            images=images,
        )

        # Bridge into the asyncio event loop.
        coro = self._callback(incoming)
        asyncio.run_coroutine_threadsafe(coro, self._loop)  # type: ignore[arg-type]

    def _download_image(self, message_id: str, file_key: str) -> bytes:
        """Download image from Lark using message resource API."""
        try:
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(file_key)
                .type("image")
                .build()
            )
            response = self._api_client.im.v1.message_resource.get(request)
            if not response.success():
                logger.error(
                    "Failed to download image: code=%s msg=%s", response.code, response.msg
                )
                return b""
            return response.file.read()
        except Exception:
            logger.exception("Error downloading image from Lark")
            return b""

    def _send_sync(self, message: OutgoingMessage) -> None:
        """Blocking send via the sync lark client."""
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(message.conversation_id)
            .msg_type("text")
            .content(json.dumps({"text": message.text}))
            .build()
        )
        request = (
            CreateMessageRequest.builder().receive_id_type("chat_id").request_body(body).build()
        )
        response = self._api_client.im.v1.message.create(request)
        if not response.success():
            logger.error(
                "Failed to send Lark message: code=%s msg=%s",
                response.code,
                response.msg,
            )
