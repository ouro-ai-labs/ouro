"""Bot server: long-connection channel lifecycle + health endpoint."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

from aiohttp import web

from bot.channel.base import Channel, IncomingMessage, OutgoingMessage
from bot.session_router import SessionRouter
from config import Config

if TYPE_CHECKING:
    from agent.agent import LoopAgent

logger = logging.getLogger(__name__)

# Periodic cleanup interval for idle sessions (seconds)
_CLEANUP_INTERVAL = 300.0


class BotServer:
    """Manages long-connection channels and routes messages to agents."""

    def __init__(
        self,
        session_router: SessionRouter,
        channels: list[Channel],
    ) -> None:
        self._router = session_router
        self._channels = channels
        self._app = web.Application()
        self._app.router.add_get("/health", self._handle_health)
        self._cleanup_task: asyncio.Task | None = None

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "active_sessions": self._router.active_session_count,
            }
        )

    async def _process_message(self, channel: Channel, msg: IncomingMessage) -> None:
        """Process a message: lock -> ack -> agent.run -> send result."""
        try:
            agent = self._router.get_or_create_agent(msg.channel, msg.conversation_id)
            lock = self._router.get_lock(msg.channel, msg.conversation_id)

            async with lock:
                await channel.send_message(
                    OutgoingMessage(
                        conversation_id=msg.conversation_id,
                        text="Working on it...",
                    )
                )

                logger.info(
                    "Processing message from %s:%s — %s",
                    msg.channel,
                    msg.conversation_id,
                    msg.text[:80],
                )
                result = await agent.run(msg.text)

                await channel.send_message(
                    OutgoingMessage(
                        conversation_id=msg.conversation_id,
                        text=result,
                    )
                )

                logger.info(
                    "Replied to %s:%s — %d chars",
                    msg.channel,
                    msg.conversation_id,
                    len(result),
                )

        except Exception:
            logger.exception(
                "Error processing message %s from %s:%s",
                msg.message_id,
                msg.channel,
                msg.conversation_id,
            )
            try:
                await channel.send_message(
                    OutgoingMessage(
                        conversation_id=msg.conversation_id,
                        text="Sorry, something went wrong while processing your message. Please try again.",
                    )
                )
            except Exception:
                logger.exception("Failed to send error message")

    async def _periodic_cleanup(self) -> None:
        """Periodically clean up idle sessions."""
        while True:
            await asyncio.sleep(_CLEANUP_INTERVAL)
            try:
                removed = self._router.cleanup_idle_sessions()
                if removed > 0:
                    logger.info("Cleaned up %d idle sessions", removed)
            except Exception:
                logger.exception("Error during session cleanup")

    async def start(self, host: str, port: int) -> None:
        """Start channels + health server, block until cancelled."""
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

        # Start each channel, giving it a callback bound to itself.
        for ch in self._channels:
            callback = self._make_callback(ch)
            await ch.start(callback)

        # Lightweight HTTP server for /health only.
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()

        channel_names = ", ".join(ch.name for ch in self._channels)
        print(f"Bot server listening on {host}:{port}", file=sys.stderr)
        print(f"  Active channels: {channel_names}", file=sys.stderr)

        try:
            await asyncio.Event().wait()
        finally:
            if self._cleanup_task:
                self._cleanup_task.cancel()
            for ch in self._channels:
                await ch.stop()
            await runner.cleanup()

    def _make_callback(self, channel: Channel):
        """Create the message callback for a specific channel."""

        async def _callback(msg: IncomingMessage) -> None:
            asyncio.create_task(self._process_message(channel, msg))

        return _callback


def _build_channels() -> list[Channel]:
    """Build channel instances from config, lazy-importing SDKs."""
    channels: list[Channel] = []

    # Feishu channel
    if Config.FEISHU_APP_ID and Config.FEISHU_APP_SECRET:
        try:
            from bot.channel.feishu import FeishuChannel

            channels.append(FeishuChannel())
            logger.info("Feishu channel enabled")
        except ImportError:
            logger.warning(
                "Feishu credentials configured but lark-oapi not installed. "
                "Install with: pip install ouro-ai[bot-feishu]"
            )
    else:
        logger.info("Feishu channel disabled (FEISHU_APP_ID / FEISHU_APP_SECRET not set)")

    # Slack channel
    if Config.SLACK_BOT_TOKEN and Config.SLACK_APP_TOKEN:
        try:
            from bot.channel.slack import SlackChannel

            channels.append(SlackChannel())
            logger.info("Slack channel enabled")
        except ImportError:
            logger.warning(
                "Slack tokens configured but slack-sdk not installed. "
                "Install with: pip install ouro-ai[bot-slack]"
            )
    else:
        logger.info("Slack channel disabled (SLACK_BOT_TOKEN / SLACK_APP_TOKEN not set)")

    return channels


async def run_bot(model_id: str | None = None) -> None:
    """Top-level entry point for bot mode.

    Args:
        model_id: Optional model ID to use for agents.
    """
    from main import create_agent

    channels = _build_channels()
    if not channels:
        print(
            "No IM channels configured. Set OURO_FEISHU_APP_ID/OURO_FEISHU_APP_SECRET "
            "or OURO_SLACK_BOT_TOKEN/OURO_SLACK_APP_TOKEN to enable a channel.",
            file=sys.stderr,
        )
        return

    def agent_factory() -> LoopAgent:
        return create_agent(model_id=model_id)

    router = SessionRouter(agent_factory=agent_factory)
    server = BotServer(session_router=router, channels=channels)

    host = Config.BOT_HOST
    port = Config.BOT_PORT
    await server.start(host, port)
