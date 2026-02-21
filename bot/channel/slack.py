"""Slack Socket Mode channel implementation for bot mode.

Uses ``slack-sdk`` ``AsyncSocketModeClient`` (aiohttp backend) which is
natively async — no thread bridging needed.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import TYPE_CHECKING

from slack_sdk.socket_mode.aiohttp import SocketModeClient as AsyncSocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

from bot.channel.base import IncomingMessage, OutgoingMessage

if TYPE_CHECKING:
    from bot.channel.base import MessageCallback

from config import Config

logger = logging.getLogger(__name__)

# Maximum number of message IDs to keep for deduplication.
_DEDUP_MAX_SIZE = 2000


class SlackChannel:
    """Slack channel backed by Socket Mode (long connection)."""

    name: str = "slack"

    def __init__(self) -> None:
        self._bot_token = Config.SLACK_BOT_TOKEN
        self._app_token = Config.SLACK_APP_TOKEN

        self._callback: MessageCallback | None = None
        self._web_client = AsyncWebClient(token=self._bot_token)
        self._socket_client: AsyncSocketModeClient | None = None

        # Bounded dedup set: OrderedDict used as an ordered set.
        self._seen: OrderedDict[str, None] = OrderedDict()

    # ------------------------------------------------------------------
    # Channel protocol
    # ------------------------------------------------------------------

    async def start(self, message_callback: MessageCallback) -> None:
        """Open the Socket Mode connection and begin dispatching messages."""
        self._callback = message_callback

        self._socket_client = AsyncSocketModeClient(
            app_token=self._app_token,
            web_client=self._web_client,
        )
        self._socket_client.socket_mode_request_listeners.append(self._on_request)

        await self._socket_client.connect()
        logger.info("Slack Socket Mode channel started")

    async def stop(self) -> None:
        """Shut down the Socket Mode connection."""
        if self._socket_client is not None:
            await self._socket_client.close()
            self._socket_client = None
        self._callback = None
        logger.info("Slack Socket Mode channel stopped")

    async def send_message(self, message: OutgoingMessage) -> None:
        """Send a text message to a Slack channel/DM."""
        resp = await self._web_client.chat_postMessage(
            channel=message.conversation_id,
            text=message.text,
        )
        if not resp.get("ok"):
            logger.error("Failed to send Slack message: %s", resp.get("error"))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _on_request(self, client: AsyncSocketModeClient, req: SocketModeRequest) -> None:
        """Handle a Socket Mode request from Slack."""
        # Always ack immediately to prevent retries.
        await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        if req.type != "events_api":
            return

        event = (req.payload or {}).get("event", {})
        if event.get("type") != "message":
            return

        # Skip bot messages, message edits/deletes, and subtypes.
        if event.get("bot_id") or event.get("subtype"):
            return

        text = (event.get("text") or "").strip()
        if not text:
            return

        # Dedup by client_msg_id (set by Slack clients).
        msg_id = event.get("client_msg_id") or event.get("ts", "")
        if self._is_duplicate(msg_id):
            logger.debug("Duplicate Slack message %s, skipping", msg_id)
            return

        channel_id = event.get("channel", "")
        user_id = event.get("user", "")

        incoming = IncomingMessage(
            channel=self.name,
            conversation_id=channel_id,
            user_id=user_id,
            text=text,
            message_id=msg_id,
            raw=req.payload or {},
        )

        if self._callback is not None:
            await self._callback(incoming)

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
