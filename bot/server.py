"""Bot server: long-connection channel lifecycle + health endpoint."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

from aiohttp import web

from bot.channel.base import Channel, IncomingMessage, OutgoingMessage
from bot.proactive import CronScheduler, HeartbeatRunner, ProactiveExecutor
from bot.session_router import SessionRouter
from config import Config

if TYPE_CHECKING:
    from agent.agent import LoopAgent

logger = logging.getLogger(__name__)

# Periodic cleanup interval for idle sessions (seconds)
_CLEANUP_INTERVAL = 300.0


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    h, remainder = divmod(s, 3600)
    m = remainder // 60
    return f"{h}h {m}m"


class BotServer:
    """Manages long-connection channels and routes messages to agents."""

    def __init__(
        self,
        session_router: SessionRouter,
        channels: list[Channel],
        *,
        heartbeat: HeartbeatRunner | None = None,
        cron_scheduler: CronScheduler | None = None,
    ) -> None:
        self._router = session_router
        self._channels = channels
        self._heartbeat = heartbeat
        self._cron_scheduler = cron_scheduler
        self._app = web.Application()
        self._app.router.add_get("/health", self._handle_health)
        self._cleanup_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._cron_task: asyncio.Task | None = None

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "active_sessions": self._router.active_session_count,
            }
        )

    # ---- Slash commands -------------------------------------------------------

    _HELP_TEXT = (
        "Available commands:\n"
        "  /new       — Start a fresh conversation (reset session)\n"
        "  /reset     — Alias for /new\n"
        "  /compact   — Compress conversation memory to save tokens\n"
        "  /status    — Show session statistics\n"
        "  /heartbeat — Show heartbeat status\n"
        "  /cron      — Manage cron jobs (list | add | remove)\n"
        "  /help      — Show this message"
    )

    async def _handle_command(
        self,
        channel: Channel,
        msg: IncomingMessage,
    ) -> bool:
        """Handle slash commands. Returns True if the message was a command."""
        text = msg.text.strip()
        if not text.startswith("/"):
            return False

        cmd = text.split()[0].lower()

        if cmd in ("/new", "/reset"):
            self._router.reset_session(msg.channel, msg.conversation_id)
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text="Session reset. Send a message to start a new conversation.",
                )
            )
            return True

        if cmd == "/compact":
            agent = await self._router.get_or_create_agent(msg.channel, msg.conversation_id)
            try:
                result = await agent.memory.compress()
            except Exception:
                logger.exception("Compression failed for %s:%s", msg.channel, msg.conversation_id)
                await channel.send_message(
                    OutgoingMessage(
                        conversation_id=msg.conversation_id,
                        text="Compression failed — please try again later.",
                    )
                )
                return True

            if result:
                reply = (
                    f"Compressed {result.original_message_count} messages — "
                    f"saved {result.token_savings} tokens "
                    f"({result.savings_percentage:.0f}%)"
                )
            else:
                reply = "Nothing to compress."
            await channel.send_message(
                OutgoingMessage(conversation_id=msg.conversation_id, text=reply)
            )
            return True

        if cmd == "/status":
            # Try to get existing agent; don't create one just for /status
            key = self._router._session_key(msg.channel, msg.conversation_id)
            agent = self._router._sessions.get(key)
            if agent is None:
                await channel.send_message(
                    OutgoingMessage(
                        conversation_id=msg.conversation_id,
                        text="No active session. Send a message to start one.",
                    )
                )
                return True

            stats = agent.memory.get_stats()
            age = self._router.get_session_age(msg.channel, msg.conversation_id)
            age_str = _format_duration(age) if age is not None else "unknown"

            lines = [
                f"Session age: {age_str}",
                f"Messages: {stats['short_term_count']}",
                f"Context tokens: {stats['current_tokens']}",
                f"Total input tokens: {stats['total_input_tokens']}",
                f"Total output tokens: {stats['total_output_tokens']}",
                f"Compressions: {stats['compression_count']}",
            ]
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text="\n".join(lines),
                )
            )
            return True

        if cmd == "/heartbeat":
            await self._handle_heartbeat_command(channel, msg)
            return True

        if cmd == "/cron":
            await self._handle_cron_command(channel, msg)
            return True

        if cmd == "/help":
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text=self._HELP_TEXT,
                )
            )
            return True

        # Unknown /command — pass through to agent as a normal message
        return False

    async def _handle_heartbeat_command(self, channel: Channel, msg: IncomingMessage) -> None:
        """Show heartbeat status."""
        if not self._heartbeat:
            text = "Heartbeat: not configured"
        elif not self._heartbeat.enabled:
            text = "Heartbeat: disabled (interval=0)"
        else:
            lines = [
                "Heartbeat: enabled",
                f"  Interval: {self._heartbeat.interval}s",
                f"  Last run: {self._heartbeat.last_run or 'never'}",
                f"  Next run: {self._heartbeat.next_run or 'pending'}",
            ]
            text = "\n".join(lines)
        await channel.send_message(OutgoingMessage(conversation_id=msg.conversation_id, text=text))

    async def _handle_cron_command(self, channel: Channel, msg: IncomingMessage) -> None:
        """Handle /cron subcommands: list, add, remove."""
        parts = msg.text.strip().split(maxsplit=2)
        sub = parts[1].lower() if len(parts) > 1 else "list"

        if sub == "list":
            await self._cron_list(channel, msg)
        elif sub == "add":
            await self._cron_add(channel, msg, parts)
        elif sub == "remove":
            await self._cron_remove(channel, msg, parts)
        else:
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text="Usage: /cron list | /cron add <schedule> <prompt> | /cron remove <id>",
                )
            )

    async def _cron_list(self, channel: Channel, msg: IncomingMessage) -> None:
        if not self._cron_scheduler:
            await channel.send_message(
                OutgoingMessage(conversation_id=msg.conversation_id, text="Cron: not configured")
            )
            return
        jobs = self._cron_scheduler.jobs
        if not jobs:
            await channel.send_message(
                OutgoingMessage(conversation_id=msg.conversation_id, text="No cron jobs.")
            )
            return
        lines = []
        for j in jobs:
            status = "on" if j.enabled else "off"
            sched = f"{j.schedule_type}={j.schedule_value}"
            lines.append(f"  [{status}] {j.id}  {sched}  {j.name}")
        await channel.send_message(
            OutgoingMessage(
                conversation_id=msg.conversation_id,
                text="Cron jobs:\n" + "\n".join(lines),
            )
        )

    async def _cron_add(self, channel: Channel, msg: IncomingMessage, parts: list[str]) -> None:
        if not self._cron_scheduler:
            await channel.send_message(
                OutgoingMessage(conversation_id=msg.conversation_id, text="Cron: not configured")
            )
            return
        # /cron add <schedule> <prompt>
        # Re-split the rest after "add" to get schedule + prompt
        rest = msg.text.strip().split(maxsplit=2)
        if len(rest) < 3:
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text="Usage: /cron add <schedule> <prompt>\n"
                    "  schedule: cron expression (e.g. '0 9 * * *') or interval in seconds",
                )
            )
            return
        add_rest = rest[2]  # everything after "/cron add"
        # First token is schedule, rest is prompt
        add_parts = add_rest.split(maxsplit=1)
        if len(add_parts) < 2:
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text="Usage: /cron add <schedule> <prompt>",
                )
            )
            return
        schedule_expr, prompt = add_parts
        try:
            job = self._cron_scheduler.add_job(schedule_expr, prompt)
        except (ValueError, KeyError) as exc:
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text=f"Invalid schedule: {exc}",
                )
            )
            return
        await channel.send_message(
            OutgoingMessage(
                conversation_id=msg.conversation_id,
                text=f"Added cron job {job.id}: next run at {job.next_run_at}",
            )
        )

    async def _cron_remove(self, channel: Channel, msg: IncomingMessage, parts: list[str]) -> None:
        if not self._cron_scheduler:
            await channel.send_message(
                OutgoingMessage(conversation_id=msg.conversation_id, text="Cron: not configured")
            )
            return
        rest = msg.text.strip().split()
        if len(rest) < 3:
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text="Usage: /cron remove <id>",
                )
            )
            return
        job_id = rest[2]
        if self._cron_scheduler.remove_job(job_id):
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text=f"Removed cron job {job_id}.",
                )
            )
        else:
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text=f"No cron job with id {job_id}.",
                )
            )

    # ---- Message processing ---------------------------------------------------

    async def _process_message(self, channel: Channel, msg: IncomingMessage) -> None:
        """Process a message: command check -> lock -> ack -> agent.run -> send result."""
        try:
            # Fast path: slash commands that don't need the agent lock
            # (/new, /help are stateless; /compact and /status acquire no external lock
            #  but are safe because they only read/mutate their own session.)
            if await self._handle_command(channel, msg):
                return

            agent = await self._router.get_or_create_agent(msg.channel, msg.conversation_id)
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

        # Start proactive background tasks
        if self._heartbeat and self._heartbeat.enabled:
            self._heartbeat_task = asyncio.create_task(self._heartbeat.loop())
        if self._cron_scheduler:
            self._cron_task = asyncio.create_task(self._cron_scheduler.loop())

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
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
            if self._cron_task:
                self._cron_task.cancel()
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

    # Lark channel
    if Config.LARK_APP_ID and Config.LARK_APP_SECRET:
        try:
            from bot.channel.lark import LarkChannel

            channels.append(LarkChannel())
            logger.info("Lark channel enabled")
        except ImportError:
            logger.warning(
                "Lark credentials configured but lark-oapi not installed. "
                "Install with: pip install ouro-ai[bot]"
            )
    else:
        logger.info("Lark channel disabled (LARK_APP_ID / LARK_APP_SECRET not set)")

    # Slack channel
    if Config.SLACK_BOT_TOKEN and Config.SLACK_APP_TOKEN:
        try:
            from bot.channel.slack import SlackChannel

            channels.append(SlackChannel())
            logger.info("Slack channel enabled")
        except ImportError:
            logger.warning(
                "Slack tokens configured but slack-sdk not installed. "
                "Install with: pip install ouro-ai[bot]"
            )
    else:
        logger.info("Slack channel disabled (SLACK_BOT_TOKEN / SLACK_APP_TOKEN not set)")

    return channels


async def run_bot(model_id: str | None = None) -> None:
    """Top-level entry point for bot mode.

    Args:
        model_id: Optional model ID to use for agents.
    """
    from agent.skills import SkillsRegistry, render_skills_section
    from bot.soul import load_soul
    from main import create_agent

    # Bot mode: enable long-term memory by default so conversations persist
    Config.LONG_TERM_MEMORY_ENABLED = True

    channels = _build_channels()
    if not channels:
        print(
            "No IM channels configured. Add LARK_APP_ID/LARK_APP_SECRET "
            "or SLACK_BOT_TOKEN/SLACK_APP_TOKEN to ~/.ouro/config.",
            file=sys.stderr,
        )
        return

    # Load bot personality (once, shared across all sessions)
    soul_content = load_soul()

    # Bootstrap bundled skills (copies defaults to ~/.ouro/skills/ if needed)
    try:
        bootstrap_registry = SkillsRegistry()
        await bootstrap_registry.load()
    except Exception as e:
        logger.warning("Failed to bootstrap skills registry: %s", e)

    # Shared state populated after CronScheduler is created, so agent_factory
    # can inject CronTool into each new agent without a circular dependency.
    _shared: dict[str, CronScheduler] = {}

    async def agent_factory() -> LoopAgent:
        agent = create_agent(model_id=model_id)
        if soul_content:
            agent.set_soul_section(soul_content)
        # Reload skills from disk each time so new sessions see newly installed skills
        try:
            registry = SkillsRegistry()
            await registry.load()
            section = render_skills_section(list(registry.skills.values()))
            if section:
                agent.set_skills_section(section)
        except Exception as e:
            logger.warning("Failed to load skills for new session: %s", e)
        # Give the agent a manage_cron tool so it can schedule tasks on behalf of the user
        if "cron" in _shared:
            from tools.cron_tool import CronTool

            agent.tool_executor.add_tool(CronTool(_shared["cron"]))
        # Give the agent a manage_heartbeat tool to edit the heartbeat checklist
        from tools.heartbeat_tool import HeartbeatTool

        agent.tool_executor.add_tool(HeartbeatTool())
        return agent

    router = SessionRouter(agent_factory=agent_factory)

    # Proactive mechanisms (heartbeat + cron)
    executor = ProactiveExecutor(agent_factory, channels, router)
    heartbeat = HeartbeatRunner(executor)
    cron = CronScheduler(executor)
    _shared["cron"] = cron

    server = BotServer(
        session_router=router,
        channels=channels,
        heartbeat=heartbeat,
        cron_scheduler=cron,
    )

    host = Config.BOT_HOST
    port = Config.BOT_PORT
    await server.start(host, port)
