"""Proactive mechanisms: heartbeat checks and cron-scheduled tasks.

All proactive tasks run in *isolated sessions* (one-shot agents without
conversation history) to keep token costs low. Results are broadcast to
all active IM sessions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from croniter import croniter

from config import Config

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent.agent import LoopAgent
    from bot.channel.base import Channel
    from bot.session_router import SessionRouter

logger = logging.getLogger(__name__)

# Paths under ~/.ouro/bot/
_BOT_DIR = os.path.join(os.path.expanduser("~"), ".ouro", "bot")
_HEARTBEAT_FILE = os.path.join(_BOT_DIR, "heartbeat.md")
_CRON_JOBS_FILE = os.path.join(_BOT_DIR, "cron_jobs.json")

# Execution timeout for isolated agent runs (seconds)
_ISOLATED_TIMEOUT = 120

_DEFAULT_HEARTBEAT = """\
# Heartbeat Checklist

This file is read every heartbeat cycle. Edit it to define periodic checks.
Use the manage_heartbeat tool to add or remove items.
"""

_HEARTBEAT_PROMPT = """\
You are running a periodic heartbeat check. This is an isolated session \
with no conversation history.

Read the following heartbeat checklist and follow it strictly. \
Do not infer tasks from prior conversations.

If nothing needs attention, respond with exactly: HEARTBEAT_OK
If something needs attention, write a concise message.

---
{checklist}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_heartbeat() -> str:
    """Load heartbeat.md, creating a default if it doesn't exist."""
    if not os.path.isfile(_HEARTBEAT_FILE):
        os.makedirs(_BOT_DIR, exist_ok=True)
        with open(_HEARTBEAT_FILE, "w", encoding="utf-8") as f:
            f.write(_DEFAULT_HEARTBEAT)
        logger.info("Created default heartbeat file: %s", _HEARTBEAT_FILE)
    try:
        with open(_HEARTBEAT_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        logger.warning("Could not read heartbeat file: %s", _HEARTBEAT_FILE, exc_info=True)
        return ""


def _has_checklist_items(text: str) -> bool:
    """Return True if *text* contains at least one ``- [ ] …`` item."""
    return any(line.strip().startswith("- [ ] ") for line in text.splitlines())


def is_active_hours(
    now: datetime | None = None,
    *,
    start: int | None = None,
    end: int | None = None,
    tz_name: str | None = None,
) -> bool:
    """Return True if the current hour falls within the active window.

    Parameters default to Config values when not explicitly provided.
    """
    start = start if start is not None else Config.BOT_ACTIVE_HOURS_START
    end = end if end is not None else Config.BOT_ACTIVE_HOURS_END
    tz_name = tz_name if tz_name is not None else Config.BOT_ACTIVE_HOURS_TZ

    if now is None:
        if tz_name:
            try:
                import zoneinfo

                tz = zoneinfo.ZoneInfo(tz_name)
            except Exception:
                tz = None
        else:
            tz = None
        now = datetime.now(tz=tz)

    hour = now.hour
    if start <= end:
        # e.g. 8–22
        return start <= hour < end
    # Wraps midnight, e.g. 22–6
    return hour >= start or hour < end


# ---------------------------------------------------------------------------
# IsolatedAgentRunner — isolated execution + broadcast
# ---------------------------------------------------------------------------


class IsolatedAgentRunner:
    """Run prompts in one-shot agent sessions and broadcast results."""

    def __init__(
        self,
        agent_factory: Callable[[], LoopAgent] | Callable[[], Awaitable[LoopAgent]],
        channels: list[Channel],
        router: SessionRouter,
    ) -> None:
        self._agent_factory = agent_factory
        self._channels = channels
        self._router = router

    async def run_isolated(self, prompt: str) -> str:
        """Create a throwaway agent, execute *prompt*, return result.

        The agent gets tools + soul + skills + LTM but no conversation history.
        Hard timeout: ``_ISOLATED_TIMEOUT`` seconds.
        """
        result = self._agent_factory()
        if asyncio.isfuture(result) or asyncio.iscoroutine(result):
            agent: LoopAgent = await result
        else:
            agent = result  # type: ignore[assignment]

        try:
            return await asyncio.wait_for(agent.run(prompt), timeout=_ISOLATED_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("Isolated agent timed out after %ds", _ISOLATED_TIMEOUT)
            return "[Proactive task timed out]"

    async def broadcast(self, text: str) -> int:
        """Push *text* to all active sessions, skipping busy ones.

        Returns the number of sessions successfully reached.
        """
        from bot.channel.base import OutgoingMessage

        sessions = self._router.iter_active_sessions()
        if not sessions:
            logger.debug("broadcast: no active sessions")
            return 0

        # Build a name→channel lookup for fast dispatch
        channel_map: dict[str, Channel] = {ch.name: ch for ch in self._channels}
        sent = 0

        for channel_name, conversation_id in sessions:
            if self._router.is_session_busy(channel_name, conversation_id):
                logger.debug(
                    "broadcast: skipping busy session %s:%s", channel_name, conversation_id
                )
                continue
            ch = channel_map.get(channel_name)
            if ch is None:
                continue
            try:
                await ch.send_message(OutgoingMessage(conversation_id=conversation_id, text=text))
                sent += 1
            except Exception:
                logger.warning(
                    "broadcast: failed to send to %s:%s",
                    channel_name,
                    conversation_id,
                    exc_info=True,
                )
        return sent


# ---------------------------------------------------------------------------
# HeartbeatScheduler
# ---------------------------------------------------------------------------


class HeartbeatScheduler:
    """Periodically execute a heartbeat check and broadcast if needed."""

    def __init__(self, executor: IsolatedAgentRunner, interval: int | None = None) -> None:
        self._executor = executor
        self._interval = interval if interval is not None else Config.BOT_HEARTBEAT_INTERVAL
        self._last_run: datetime | None = None
        self._next_run: datetime | None = None
        self._running = False

    # Expose for /heartbeat command
    @property
    def interval(self) -> int:
        return self._interval

    @property
    def last_run(self) -> datetime | None:
        return self._last_run

    @property
    def next_run(self) -> datetime | None:
        return self._next_run

    @property
    def enabled(self) -> bool:
        return self._interval > 0

    async def loop(self) -> None:
        """Main heartbeat loop — runs until cancelled."""
        if not self.enabled:
            logger.info("Heartbeat disabled (interval=0)")
            return
        self._running = True
        logger.info("Heartbeat started (interval=%ds)", self._interval)
        try:
            while True:
                self._next_run = datetime.now(tz=timezone.utc) + _td(self._interval)
                await asyncio.sleep(self._interval)
                await self._tick()
        except asyncio.CancelledError:
            logger.info("Heartbeat loop cancelled")
        finally:
            self._running = False

    async def _tick(self) -> None:
        """Single heartbeat tick."""
        try:
            if not is_active_hours():
                logger.debug("Heartbeat skipped: outside active hours")
                return

            # Skip if all sessions are busy
            sessions = self._executor._router.iter_active_sessions()
            if sessions and all(
                self._executor._router.is_session_busy(ch, cid) for ch, cid in sessions
            ):
                logger.debug("Heartbeat skipped: all sessions busy")
                return

            self._last_run = datetime.now(tz=timezone.utc)
            checklist = load_heartbeat()

            if not _has_checklist_items(checklist):
                logger.debug("Heartbeat skipped: checklist has no items")
                return

            prompt = _HEARTBEAT_PROMPT.format(checklist=checklist)
            result = await self._executor.run_isolated(prompt)

            if "HEARTBEAT_OK" in result:
                logger.info("Heartbeat: OK (nothing to report)")
                return

            count = await self._executor.broadcast(f"[Heartbeat] {result}")
            logger.info("Heartbeat: broadcast to %d sessions", count)
        except Exception:
            logger.exception("Heartbeat tick failed")


# ---------------------------------------------------------------------------
# CronScheduler
# ---------------------------------------------------------------------------


@dataclass
class CronJob:
    """A single scheduled job."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    schedule_type: str = "cron"  # "cron" | "every" | "once"
    schedule_value: str = ""  # cron expression | seconds | ISO datetime
    prompt: str = ""
    enabled: bool = True
    last_run_at: str | None = None
    next_run_at: str | None = None


class CronScheduler:
    """Run cron-scheduled prompts via IsolatedAgentRunner."""

    def __init__(self, executor: IsolatedAgentRunner) -> None:
        self._executor = executor
        self._jobs: list[CronJob] = []
        self._running = False
        self._load_jobs()

    # ---- Public API for slash commands -------------------------------------

    @property
    def jobs(self) -> list[CronJob]:
        return list(self._jobs)

    def add_job(
        self,
        schedule_expr: str,
        prompt: str,
        name: str = "",
    ) -> CronJob:
        """Add a new job.

        *schedule_expr* is an integer (seconds), an ISO datetime (once), or
        a cron expression.
        """
        try:
            seconds = int(schedule_expr)
            stype, sval = "every", str(seconds)
        except ValueError:
            try:
                dt = datetime.fromisoformat(schedule_expr)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                stype, sval = "once", dt.isoformat()
            except ValueError:
                # Validate cron expression
                croniter(schedule_expr)  # raises ValueError on bad expr
                stype, sval = "cron", schedule_expr

        job = CronJob(
            name=name or prompt[:40],
            schedule_type=stype,
            schedule_value=sval,
            prompt=prompt,
        )
        self._compute_next_run(job)
        self._jobs.append(job)
        self._save_jobs()
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID. Returns True if found."""
        before = len(self._jobs)
        self._jobs = [j for j in self._jobs if j.id != job_id]
        removed = len(self._jobs) < before
        if removed:
            self._save_jobs()
        return removed

    # ---- Loop --------------------------------------------------------------

    async def loop(self) -> None:
        """Main scheduler loop — checks every 60s."""
        self._running = True
        logger.info("Cron scheduler started (%d jobs loaded)", len(self._jobs))
        try:
            while True:
                await asyncio.sleep(60)
                await self._tick()
        except asyncio.CancelledError:
            logger.info("Cron scheduler cancelled")
        finally:
            self._running = False

    async def _tick(self) -> None:
        """Check all jobs, execute those that are due."""
        now = datetime.now(tz=timezone.utc)
        for job in self._jobs:
            if not job.enabled or not job.next_run_at:
                continue
            try:
                next_dt = datetime.fromisoformat(job.next_run_at)
            except (ValueError, TypeError):
                continue
            if now < next_dt:
                continue

            if not is_active_hours():
                logger.debug("Cron job %s skipped: outside active hours", job.id)
                self._compute_next_run(job)
                continue

            await self._execute_job(job)

    async def _execute_job(self, job: CronJob) -> None:
        """Execute a single job and broadcast the result."""
        try:
            logger.info("Cron executing job %s (%s)", job.id, job.name)
            result = await self._executor.run_isolated(job.prompt)
            label = job.name or job.id
            await self._executor.broadcast(f"[Cron: {label}] {result}")
        except Exception:
            logger.exception("Cron job %s failed", job.id)
        finally:
            job.last_run_at = datetime.now(tz=timezone.utc).isoformat()
            if job.schedule_type == "once":
                self._jobs = [j for j in self._jobs if j.id != job.id]
            else:
                self._compute_next_run(job)
            self._save_jobs()

    # ---- Persistence -------------------------------------------------------

    def _compute_next_run(self, job: CronJob) -> None:
        """Set job.next_run_at based on schedule type."""
        now = datetime.now(tz=timezone.utc)
        try:
            if job.schedule_type == "once":
                job.next_run_at = job.schedule_value  # already ISO
                return
            if job.schedule_type == "every":
                seconds = int(job.schedule_value)
                nxt = now + _td(seconds)
            else:
                cron = croniter(job.schedule_value, now)
                nxt = cron.get_next(datetime)
            job.next_run_at = nxt.isoformat()
        except Exception:
            logger.warning("Cannot compute next_run for job %s", job.id, exc_info=True)
            job.next_run_at = None

    def _save_jobs(self) -> None:
        """Persist jobs to ~/.ouro/bot/cron_jobs.json."""
        os.makedirs(_BOT_DIR, exist_ok=True)
        data = [asdict(j) for j in self._jobs]
        try:
            with open(_CRON_JOBS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            logger.warning("Failed to save cron jobs", exc_info=True)

    def _load_jobs(self) -> None:
        """Load jobs from disk."""
        if not os.path.isfile(_CRON_JOBS_FILE):
            return
        try:
            with open(_CRON_JOBS_FILE, encoding="utf-8") as f:
                data: list[dict[str, Any]] = json.load(f)
            for item in data:
                job = CronJob(
                    **{k: v for k, v in item.items() if k in CronJob.__dataclass_fields__}
                )
                self._jobs.append(job)
            logger.info("Loaded %d cron jobs from disk", len(self._jobs))
        except Exception:
            logger.warning("Failed to load cron jobs", exc_info=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _td(seconds: int):
    """Shorthand for timedelta."""
    from datetime import timedelta

    return timedelta(seconds=seconds)
