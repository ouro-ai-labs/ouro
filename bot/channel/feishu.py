"""Feishu/Lark WebSocket channel implementation for bot mode.

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
    P2ImMessageReceiveV1,
)

from bot.channel.base import IncomingMessage, OutgoingMessage

if TYPE_CHECKING:
    from bot.channel.base import MessageCallback

from config import Config

logger = logging.getLogger(__name__)


class FeishuChannel:
    """Feishu/Lark channel backed by a WebSocket long connection."""

    name: str = "feishu"

    def __init__(self) -> None:
        self._app_id = Config.FEISHU_APP_ID
        self._app_secret = Config.FEISHU_APP_SECRET

        self._callback: MessageCallback | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws_client: lark.ws.Client | None = None
        self._thread: threading.Thread | None = None

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

        # lark.ws.Client.start() blocks — run in a daemon thread.
        self._thread = threading.Thread(
            target=self._ws_client.start,
            daemon=True,
            name="feishu-ws",
        )
        self._thread.start()
        logger.info("Feishu WebSocket channel started")

    async def stop(self) -> None:
        """Shut down the WebSocket connection."""
        # The SDK doesn't expose a public stop(); the daemon thread will be
        # reaped on process exit.  Clear internal references.
        self._ws_client = None
        self._callback = None
        self._loop = None
        logger.info("Feishu WebSocket channel stopped")

    async def send_message(self, message: OutgoingMessage) -> None:
        """Send a text message to a Feishu chat (async-safe)."""
        await asyncio.to_thread(self._send_sync, message)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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

        # Only handle text messages for MVP.
        if msg_obj.message_type != "text":
            logger.debug("Ignoring message type: %s", msg_obj.message_type)
            return

        # Parse text content (Feishu wraps it in JSON: {"text": "hello"}).
        try:
            content = json.loads(msg_obj.content or "{}")
            text = content.get("text", "")
        except json.JSONDecodeError:
            text = msg_obj.content or ""

        if not text.strip():
            return

        incoming = IncomingMessage(
            channel=self.name,
            conversation_id=msg_obj.chat_id or "",
            user_id=(sender.sender_id.open_id if sender.sender_id else "") or "",
            text=text.strip(),
            message_id=msg_obj.message_id or "",
        )

        # Bridge into the asyncio event loop.
        coro = self._callback(incoming)
        asyncio.run_coroutine_threadsafe(coro, self._loop)  # type: ignore[arg-type]

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
                "Failed to send Feishu message: code=%s msg=%s",
                response.code,
                response.msg,
            )
