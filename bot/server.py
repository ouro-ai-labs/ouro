"""Bot server: long-connection channel lifecycle + health endpoint."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

from aiohttp import web

from bot.channel.base import Channel, IncomingMessage, OutgoingMessage
from bot.message_queue import ConversationQueue, coalesce_messages
from bot.proactive import CronScheduler, HeartbeatScheduler, IsolatedAgentRunner
from bot.session_router import SessionRouter
from config import Config

if TYPE_CHECKING:
    from agent.agent import LoopAgent

logger = logging.getLogger(__name__)

# Periodic cleanup interval for stale sessions on disk (seconds, 6 hours)
_CLEANUP_INTERVAL = 21600.0


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
        heartbeat: HeartbeatScheduler | None = None,
        cron_scheduler: CronScheduler | None = None,
        debounce_seconds: float = 1.5,
        max_batch_size: int = 20,
    ) -> None:
        self._router = session_router
        self._channels = channels
        self._heartbeat = heartbeat
        self._cron_scheduler = cron_scheduler
        self._debounce = debounce_seconds
        self._max_batch = max_batch_size
        self._app = web.Application()
        self._app.router.add_get("/health", self._handle_health)
        self._cleanup_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._cron_task: asyncio.Task | None = None

        # Channel lookup for batch processing
        self._channel_map: dict[str, Channel] = {ch.name: ch for ch in channels}
        # Per-conversation queues (created lazily)
        self._queues: dict[str, ConversationQueue] = {}
        # Tracks reaction IDs for 👀 cleanup: platform_message_id -> reaction_id
        self._reaction_ids: dict[str, str | None] = {}

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
        "  /sessions  — List or resume saved sessions\n"
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
            await self._router.reset_session(msg.channel, msg.conversation_id)
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

        if cmd == "/sessions":
            await self._handle_sessions_command(channel, msg)
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

    async def _handle_sessions_command(self, channel: Channel, msg: IncomingMessage) -> None:
        """Handle /sessions subcommands: list, resume."""
        parts = msg.text.strip().split(maxsplit=2)
        sub = parts[1].lower() if len(parts) > 1 else "list"

        if sub == "list":
            await self._sessions_list(channel, msg)
        elif sub == "resume":
            target = parts[2].strip() if len(parts) > 2 else ""
            await self._sessions_resume(channel, msg, target)
        else:
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text="Usage: /sessions list | /sessions resume <id-prefix>",
                )
            )

    async def _sessions_list(self, channel: Channel, msg: IncomingMessage) -> None:
        """List persisted sessions."""
        try:
            sessions = await self._router.list_persisted_sessions(limit=10)
        except Exception:
            logger.exception("Failed to list sessions")
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text="Failed to list sessions.",
                )
            )
            return

        if not sessions:
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text="No saved sessions.",
                )
            )
            return

        lines = ["Saved sessions:"]
        for s in sessions:
            sid = s["id"][:8]
            updated = s.get("updated_at", "?")[:19]
            count = s.get("message_count", 0)
            preview = s.get("preview", "")[:50]
            if preview:
                preview = f'  "{preview}"'
            lines.append(f"  {sid}  {updated}  {count} msgs{preview}")
        lines.append("\nUse /sessions resume <id-prefix> to switch.")
        await channel.send_message(
            OutgoingMessage(
                conversation_id=msg.conversation_id,
                text="\n".join(lines),
            )
        )

    async def _sessions_resume(self, channel: Channel, msg: IncomingMessage, target: str) -> None:
        """Resume a persisted session by ID prefix."""
        if not target:
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text="Usage: /sessions resume <id-prefix>",
                )
            )
            return

        full_id = await self._router.find_session_by_prefix(target)
        if not full_id:
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text=f"No session found matching '{target}'.",
                )
            )
            return

        # Save current session before switching
        try:
            await self._router.save_session(msg.channel, msg.conversation_id)
        except Exception:
            logger.warning("Failed to save current session before resume", exc_info=True)

        # Reset and create a new agent, then load the target session
        await self._router.reset_session(msg.channel, msg.conversation_id)
        agent = await self._router.get_or_create_agent(msg.channel, msg.conversation_id)

        try:
            await agent.load_session(full_id)
        except Exception:
            logger.exception("Failed to resume session %s", full_id[:8])
            await channel.send_message(
                OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text=f"Failed to resume session {full_id[:8]}.",
                )
            )
            return

        # Update the conversation map to point to the resumed session
        await self._router.update_session_mapping(msg.channel, msg.conversation_id)

        await channel.send_message(
            OutgoingMessage(
                conversation_id=msg.conversation_id,
                text=f"Resumed session {full_id[:8]}. Send a message to continue.",
            )
        )

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

    # Emoji constants for reaction-based acknowledgment.
    _PROCESSING_EMOJI = "eyes"
    _DONE_EMOJI = "white_check_mark"

    async def _process_message(self, channel: Channel, msg: IncomingMessage) -> None:
        """Command check -> 👀 reaction -> enqueue for debounced batch processing."""
        try:
            if await self._handle_command(channel, msg):
                return

            # Instant feedback: add 👀 so the user knows we received it
            await self._try_add_processing_reaction(channel, msg)

            # Route to per-conversation queue (created lazily)
            key = f"{channel.name}:{msg.conversation_id}"
            if key not in self._queues:
                self._queues[key] = ConversationQueue(
                    key,
                    self._process_batch,
                    debounce_seconds=self._debounce,
                    max_batch_size=self._max_batch,
                )
            await self._queues[key].enqueue(msg)
        except Exception:
            logger.exception(
                "Error enqueueing %s from %s:%s", msg.message_id, msg.channel, msg.conversation_id
            )

    async def _try_add_processing_reaction(self, channel: Channel, msg: IncomingMessage) -> None:
        """Add 👀 reaction and track the reaction ID for later cleanup."""
        if not msg.platform_message_id:
            return
        try:
            rid = await channel.add_reaction(
                msg.conversation_id, msg.platform_message_id, self._PROCESSING_EMOJI
            )
            self._reaction_ids[msg.platform_message_id] = rid
        except Exception:
            logger.debug("Failed to add processing reaction", exc_info=True)

    async def _process_batch(self, messages: list[IncomingMessage]) -> None:
        """Process a batch of messages: coalesce -> agent.run -> send result -> swap reactions."""
        first = messages[0]
        channel = self._channel_map.get(first.channel)
        if channel is None:
            logger.error("No channel found for %s", first.channel)
            return

        try:
            agent = await self._router.get_or_create_agent(first.channel, first.conversation_id)

            # Coalesce text; collect all images and files
            task_text = coalesce_messages(messages)
            all_images = [img for m in messages for img in m.images]
            all_files = [f for m in messages for f in m.files]

            # Save attachments to temp dir so the agent can read them
            tmp_dir: str | None = None
            if all_files or all_images:
                import tempfile
                from pathlib import Path

                tmp_dir = tempfile.mkdtemp(prefix="ouro_files_")
                for fa in all_files:
                    dest = Path(tmp_dir) / fa.filename
                    dest.write_bytes(fa.data)
                    task_text += (
                        f"\n[Attached file: {fa.filename} ({fa.mime_type}) saved at: {dest}]"
                    )
                for idx, img in enumerate(all_images):
                    ext = img.mime_type.split("/")[-1] if img.mime_type else "png"
                    img_name = f"image_{idx}.{ext}"
                    dest = Path(tmp_dir) / img_name
                    dest.write_bytes(img.data)
                    task_text += (
                        f"\n[Attached image: {img_name} ({img.mime_type}) saved at: {dest}]"
                    )

            # Wire send_file context if agent has one
            send_file_ctx = getattr(agent, "_send_file_ctx", None)
            if send_file_ctx is not None:

                async def _send_fn(
                    file_path: str | None = None,
                    file_bytes: bytes | None = None,
                    filename: str | None = None,
                    mime_type: str | None = None,
                ) -> bool:
                    return await channel.send_file(
                        conversation_id=first.conversation_id,
                        file_path=file_path,
                        file_bytes=file_bytes,
                        filename=filename,
                        mime_type=mime_type,
                    )

                send_file_ctx.set_send_fn(_send_fn)

            logger.info(
                "Processing %d message(s) from %s:%s — %s",
                len(messages),
                first.channel,
                first.conversation_id,
                task_text[:80],
            )
            try:
                result = await agent.run(task_text, images=all_images or None)
            finally:
                if send_file_ctx is not None:
                    send_file_ctx.clear()
                if tmp_dir is not None:
                    import shutil

                    shutil.rmtree(tmp_dir, ignore_errors=True)

            await self._router.update_session_mapping(first.channel, first.conversation_id)
            await channel.send_message(
                OutgoingMessage(conversation_id=first.conversation_id, text=result)
            )
            logger.info(
                "Replied to %s:%s — %d chars", first.channel, first.conversation_id, len(result)
            )

            # Swap reactions on ALL source messages: 👀 → ✅
            await self._finalize_reactions(channel, messages, done=True)

        except Exception:
            logger.exception(
                "Error processing batch from %s:%s", first.channel, first.conversation_id
            )
            await self._finalize_reactions(channel, messages, done=False)
            try:
                await channel.send_message(
                    OutgoingMessage(
                        conversation_id=first.conversation_id,
                        text="Sorry, something went wrong while processing your message. Please try again.",
                    )
                )
            except Exception:
                logger.exception("Failed to send error message")

    async def _finalize_reactions(
        self, channel: Channel, messages: list[IncomingMessage], *, done: bool
    ) -> None:
        """Remove 👀 from all batch messages; add ✅ if *done*."""
        for msg in messages:
            pid = msg.platform_message_id
            if not pid:
                continue
            rid = self._reaction_ids.pop(pid, None)
            await self._safe_reaction(
                channel.remove_reaction(msg.conversation_id, pid, self._PROCESSING_EMOJI, rid)
            )
            if done:
                await self._safe_reaction(
                    channel.add_reaction(msg.conversation_id, pid, self._DONE_EMOJI)
                )

    @staticmethod
    async def _safe_reaction(coro) -> None:  # type: ignore[type-arg]
        """Await a reaction coroutine, swallowing errors."""
        try:
            await coro
        except Exception:
            logger.debug("Reaction operation failed", exc_info=True)

    async def _periodic_cleanup(self) -> None:
        """Periodically delete stale sessions from disk."""
        while True:
            await asyncio.sleep(_CLEANUP_INTERVAL)
            try:
                removed = await self._router.cleanup_stale_sessions()
                if removed > 0:
                    logger.info("Cleaned up %d stale sessions from disk", removed)
            except Exception:
                logger.exception("Error during stale session cleanup")

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
            for q in self._queues.values():
                q.shutdown()
            self._queues.clear()
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
    from pathlib import Path

    from agent.skills import SkillsRegistry, render_skills_section
    from bot.soul import load_soul
    from main import create_agent
    from utils.runtime import (
        ensure_bot_dirs,
        get_bot_memory_dir,
        get_bot_sessions_dir,
        get_bot_skills_dir,
    )

    # Bot mode: enable long-term memory by default so conversations persist
    Config.LONG_TERM_MEMORY_ENABLED = True

    # Ensure bot-specific directories exist
    ensure_bot_dirs()
    bot_sessions_dir = get_bot_sessions_dir()
    bot_memory_dir = get_bot_memory_dir()
    bot_skills_dir = Path(get_bot_skills_dir())

    # Tell skill-installer scripts to write into the bot skills directory
    import os

    os.environ["OURO_SKILLS_DIR"] = str(bot_skills_dir)

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

    # Bootstrap bundled skills into bot's own skills directory
    try:
        bootstrap_registry = SkillsRegistry(skills_dir=bot_skills_dir, bootstrap=True)
        await bootstrap_registry.load()
    except Exception as e:
        logger.warning("Failed to bootstrap skills registry: %s", e)

    # Shared state populated after CronScheduler is created, so agent_factory
    # can inject CronTool into each new agent without a circular dependency.
    _shared: dict[str, CronScheduler] = {}

    async def agent_factory() -> LoopAgent:
        agent = create_agent(
            model_id=model_id,
            sessions_dir=bot_sessions_dir,
            memory_dir=bot_memory_dir,
        )
        if soul_content:
            agent.set_soul_section(soul_content)
        # Reload skills from disk each time so new sessions see newly installed skills
        try:
            registry = SkillsRegistry(skills_dir=bot_skills_dir)
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
        # Inject heartbeat content into system prompt so the agent sees it
        from bot.proactive import load_heartbeat

        hb_content = load_heartbeat()
        if hb_content:
            agent.set_heartbeat_section(hb_content)

        # Give the agent a send_file tool (context is set per-batch in _process_batch)
        from tools.send_file_tool import SendFileContext, SendFileTool

        ctx = SendFileContext()
        agent.tool_executor.add_tool(SendFileTool(ctx))
        agent._send_file_ctx = ctx  # type: ignore[attr-defined]  # stash for _process_batch

        return agent

    router = SessionRouter(
        agent_factory=agent_factory,
        sessions_dir=bot_sessions_dir,
    )
    await router.load_conversation_map()

    # Proactive mechanisms (heartbeat + cron)
    executor = IsolatedAgentRunner(agent_factory, channels, router)
    heartbeat = HeartbeatScheduler(executor)
    cron = CronScheduler(executor)
    _shared["cron"] = cron

    server = BotServer(
        session_router=router,
        channels=channels,
        heartbeat=heartbeat,
        cron_scheduler=cron,
        debounce_seconds=Config.BOT_DEBOUNCE_SECONDS,
        max_batch_size=Config.BOT_MAX_BATCH_SIZE,
    )

    host = Config.BOT_HOST
    port = Config.BOT_PORT
    await server.start(host, port)
