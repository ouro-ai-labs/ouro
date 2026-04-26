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

from ouro.interfaces.bot.channel.base import FileAttachment, ImageData, IncomingMessage, OutgoingMessage

if TYPE_CHECKING:
    from ouro.interfaces.bot.channel.base import MessageCallback

from ouro.config import Config

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
        self._bot_user_id: str = ""

        # Bounded dedup set: OrderedDict used as an ordered set.
        self._seen: OrderedDict[str, None] = OrderedDict()

    # ------------------------------------------------------------------
    # Channel protocol
    # ------------------------------------------------------------------

    async def start(self, message_callback: MessageCallback) -> None:
        """Open the Socket Mode connection and begin dispatching messages."""
        self._callback = message_callback

        # Fetch the bot's own user ID for mention filtering.
        try:
            auth_resp = await self._web_client.auth_test()
            self._bot_user_id = auth_resp.get("user_id", "") or ""
            logger.info("Fetched bot user_id: %s", self._bot_user_id)
        except Exception:
            logger.warning(
                "Could not fetch bot user ID — mention filtering may not work", exc_info=True
            )

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

        # Skip bot messages, message edits/deletes, and subtypes
        # (but allow "file_share" subtype so image-only messages come through).
        subtype = event.get("subtype")
        if event.get("bot_id") or (subtype and subtype != "file_share"):
            return

        text = (event.get("text") or "").strip()

        # --- Download file attachments (images + other files) ---
        images: list[ImageData] = []
        files: list[FileAttachment] = []
        for f in event.get("files", []):
            mime = f.get("mimetype", "")
            url = f.get("url_private_download") or f.get("url_private", "")
            if not url:
                continue
            if mime.startswith("image/"):
                img_data = await self._download_file(url)
                if img_data:
                    images.append(ImageData(data=img_data, mime_type=mime))
            else:
                file_data = await self._download_file(url)
                if file_data:
                    fname = f.get("name", "attachment")
                    files.append(FileAttachment(data=file_data, filename=fname, mime_type=mime))

        # --- @ mention filtering for group/channel messages ---
        channel_type = event.get("channel_type", "")
        if channel_type != "im" and self._bot_user_id:
            mention_tag = f"<@{self._bot_user_id}>"
            if mention_tag not in text:
                return
            text = text.replace(mention_tag, "").strip()

        if not text and not images and not files:
            return

        # Dedup by client_msg_id (set by Slack clients).
        msg_id = event.get("client_msg_id") or event.get("ts", "")
        if self._is_duplicate(msg_id):
            logger.debug("Duplicate Slack message %s, skipping", msg_id)
            return

        channel_id = event.get("channel", "")
        user_id = event.get("user", "")

        ts = event.get("ts", "")

        incoming = IncomingMessage(
            channel=self.name,
            conversation_id=channel_id,
            user_id=user_id,
            text=text,
            message_id=msg_id,
            raw=req.payload or {},
            images=images,
            files=files,
            platform_message_id=ts,
        )

        if self._callback is not None:
            await self._callback(incoming)

    async def add_reaction(self, conversation_id: str, message_id: str, emoji: str) -> str | None:
        """Add an emoji reaction to a Slack message."""
        try:
            resp = await self._web_client.reactions_add(
                channel=conversation_id, name=emoji, timestamp=message_id
            )
            if not resp.get("ok"):
                logger.warning("Failed to add Slack reaction: %s", resp.get("error"))
        except Exception:
            logger.warning("Error adding Slack reaction", exc_info=True)
        return None

    async def remove_reaction(
        self,
        conversation_id: str,
        message_id: str,
        emoji: str,
        reaction_id: str | None = None,
    ) -> None:
        """Remove an emoji reaction from a Slack message."""
        try:
            resp = await self._web_client.reactions_remove(
                channel=conversation_id, name=emoji, timestamp=message_id
            )
            if not resp.get("ok"):
                logger.warning("Failed to remove Slack reaction: %s", resp.get("error"))
        except Exception:
            logger.warning("Error removing Slack reaction", exc_info=True)

    async def send_typing(self, conversation_id: str) -> None:
        """Slack has no typing indicator via Socket Mode — no-op."""

    async def stop_typing(self, conversation_id: str) -> None:
        """Slack has no typing indicator via Socket Mode — no-op."""

    async def send_file(
        self,
        conversation_id: str,
        file_path: str | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        mime_type: str | None = None,
    ) -> bool:
        """Upload and send a file to a Slack channel/DM."""
        try:
            kwargs: dict[str, object] = {"channel": conversation_id}
            if file_path is not None:
                kwargs["file"] = file_path
                kwargs["filename"] = filename or file_path.rsplit("/", 1)[-1]
            elif file_bytes is not None:
                kwargs["content"] = file_bytes
                kwargs["filename"] = filename or "file"
            else:
                logger.error("send_file called with neither file_path nor file_bytes")
                return False
            resp = await self._web_client.files_upload_v2(**kwargs)
            if not resp.get("ok"):
                logger.error("Failed to upload Slack file: %s", resp.get("error"))
                return False
            return True
        except Exception:
            logger.exception("Error uploading file to Slack")
            return False

    async def _download_file(self, url: str) -> bytes | None:
        """Download a file from Slack using bot token for auth."""
        import aiohttp

        headers = {"Authorization": f"Bearer {self._bot_token}"}
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp,
            ):
                if resp.status == 200:
                    return await resp.read()
                logger.error("Failed to download Slack file: status=%d", resp.status)
        except Exception:
            logger.exception("Error downloading Slack file")
        return None

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
