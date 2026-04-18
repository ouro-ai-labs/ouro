"""Proactive mechanisms: cron-scheduled tasks.

Cron jobs can run in three session modes:

- ``main``: run inside the most recently active IM session (reuses its agent
  + conversation history). If no session is active, the tick is skipped.
- ``isolated``: create a throwaway one-shot agent (no conversation history;
  tools + soul + skills + LTM only).
- ``current``: run inside a specific session bound at job-creation time
  (``bound_channel`` + ``bound_conversation_id``). Used when a user says
  "schedule this for me in *this* chat".

Delivery is orthogonal to execution:

- ``auto`` (default): for ``main``/``current`` deliver to the session that ran;
  for ``isolated`` broadcast to all active sessions.
- ``broadcast``: send to every active session.
- ``announce:<channel>:<conversation_id>``: send to one specific target.
- ``none``: suppress delivery.
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
_CRON_JOBS_FILE = os.path.join(_BOT_DIR, "cron_jobs.json")

# Execution timeout for cron agent runs (seconds).
_ISOLATED_TIMEOUT = Config.BOT_PROACTIVE_TIMEOUT


# ---------------------------------------------------------------------------
# ProactiveExecutor — runs prompts per session mode + handles delivery
# ---------------------------------------------------------------------------


class ProactiveExecutor:
    """Execute cron prompts in the requested session mode and deliver output."""

    def __init__(
        self,
        agent_factory: Callable[[], LoopAgent] | Callable[[], Awaitable[LoopAgent]],
        channels: list[Channel],
        router: SessionRouter,
    ) -> None:
        self._agent_factory = agent_factory
        self._channels = channels
        self._router = router

    # ---- Execution ---------------------------------------------------------

    async def run_isolated(self, prompt: str) -> str:
        """Create a throwaway agent, execute *prompt*, return its output."""
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

    async def run_in_session(self, channel: str, conversation_id: str, prompt: str) -> str:
        """Run *prompt* inside the existing session's agent (reuses history)."""
        agent = await self._router.get_or_create_agent(channel, conversation_id)
        try:
            return await asyncio.wait_for(agent.run(prompt), timeout=_ISOLATED_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(
                "Session agent timed out after %ds (%s:%s)",
                _ISOLATED_TIMEOUT,
                channel,
                conversation_id,
            )
            return "[Proactive task timed out]"

    # ---- Delivery ----------------------------------------------------------

    async def broadcast(self, text: str) -> int:
        """Push *text* to every active session. Returns count of successful sends."""
        from bot.channel.base import OutgoingMessage

        sessions = self._router.iter_active_sessions()
        if not sessions:
            logger.debug("broadcast: no active sessions")
            return 0

        channel_map: dict[str, Channel] = {ch.name: ch for ch in self._channels}
        sent = 0
        for channel_name, conversation_id in sessions:
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

    async def send_to(self, channel_name: str, conversation_id: str, text: str) -> bool:
        """Send *text* to one specific channel + conversation. Returns success."""
        from bot.channel.base import OutgoingMessage

        channel_map: dict[str, Channel] = {ch.name: ch for ch in self._channels}
        ch = channel_map.get(channel_name)
        if ch is None:
            logger.warning("send_to: unknown channel %s", channel_name)
            return False
        try:
            await ch.send_message(OutgoingMessage(conversation_id=conversation_id, text=text))
            return True
        except Exception:
            logger.warning(
                "send_to: failed to send to %s:%s", channel_name, conversation_id, exc_info=True
            )
            return False


# Backwards-compatible alias (kept while external callers / tests still import
# the old name).
IsolatedAgentRunner = ProactiveExecutor


# ---------------------------------------------------------------------------
# CronScheduler
# ---------------------------------------------------------------------------


_SESSION_MODES = {"main", "isolated", "current"}
_DELIVERY_LITERALS = {"auto", "broadcast", "none"}


def _validate_session_mode(mode: str) -> str:
    if mode not in _SESSION_MODES:
        raise ValueError(f"Invalid session_mode {mode!r}; must be one of {sorted(_SESSION_MODES)}")
    return mode


def _validate_delivery(delivery: str) -> str:
    if delivery in _DELIVERY_LITERALS:
        return delivery
    if delivery.startswith("announce:"):
        parts = delivery.split(":", 2)
        if len(parts) != 3 or not parts[1] or not parts[2]:
            raise ValueError(
                f"Invalid delivery {delivery!r}; expected announce:<channel>:<conversation_id>"
            )
        return delivery
    raise ValueError(
        f"Invalid delivery {delivery!r}; expected one of "
        f"{sorted(_DELIVERY_LITERALS)} or announce:<channel>:<conversation_id>"
    )


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

    # Default is "isolated" so pre-refactor persisted jobs (missing this field)
    # keep their old behavior. New jobs should pass session_mode explicitly via
    # add_job(); its default is "main".
    session_mode: str = "isolated"
    bound_channel: str | None = None
    bound_conversation_id: str | None = None
    delivery: str = "auto"


class CronScheduler:
    """Run cron-scheduled prompts via ProactiveExecutor."""

    def __init__(self, executor: ProactiveExecutor) -> None:
        self._executor = executor
        self._jobs: list[CronJob] = []
        self._running = False
        self._load_jobs()

    # ---- Public API --------------------------------------------------------

    @property
    def jobs(self) -> list[CronJob]:
        return list(self._jobs)

    def add_job(
        self,
        schedule_expr: str,
        prompt: str,
        name: str = "",
        *,
        session_mode: str = "main",
        bound_channel: str | None = None,
        bound_conversation_id: str | None = None,
        delivery: str = "auto",
    ) -> CronJob:
        """Add a new job.

        Defaults to ``session_mode="main"`` (run in the most recently active IM
        session) with ``delivery="auto"`` (reply goes back to that session).
        """
        session_mode = _validate_session_mode(session_mode)
        delivery = _validate_delivery(delivery)
        if session_mode == "current" and (not bound_channel or not bound_conversation_id):
            raise ValueError(
                "session_mode='current' requires bound_channel and bound_conversation_id"
            )

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
                croniter(schedule_expr)  # raises ValueError on bad expr
                stype, sval = "cron", schedule_expr

        job = CronJob(
            name=name or prompt[:40],
            schedule_type=stype,
            schedule_value=sval,
            prompt=prompt,
            session_mode=session_mode,
            bound_channel=bound_channel,
            bound_conversation_id=bound_conversation_id,
            delivery=delivery,
        )
        self._compute_next_run(job)
        self._jobs.append(job)
        self._save_jobs()
        return job

    def remove_job(self, job_id: str) -> bool:
        before = len(self._jobs)
        self._jobs = [j for j in self._jobs if j.id != job_id]
        removed = len(self._jobs) < before
        if removed:
            self._save_jobs()
        return removed

    # ---- Loop --------------------------------------------------------------

    async def loop(self) -> None:
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
            await self._execute_job(job)

    async def _execute_job(self, job: CronJob) -> None:
        """Run a job and deliver its output per session_mode + delivery."""
        try:
            logger.info("Cron executing job %s (%s, mode=%s)", job.id, job.name, job.session_mode)
            outcome = await self._run_for_mode(job)
            if outcome is None:
                logger.info(
                    "Cron job %s (%s): skipped (no target session for mode=%s)",
                    job.id,
                    job.name,
                    job.session_mode,
                )
                return
            result, ran_in = outcome
            await self._deliver(job, result, ran_in)
        except Exception:
            logger.exception("Cron job %s failed", job.id)
        finally:
            job.last_run_at = datetime.now(tz=timezone.utc).isoformat()
            if job.schedule_type == "once":
                self._jobs = [j for j in self._jobs if j.id != job.id]
            else:
                self._compute_next_run(job)
            self._save_jobs()

    async def _run_for_mode(self, job: CronJob) -> tuple[str, tuple[str, str] | None] | None:
        """Execute the job per its session_mode.

        Returns ``(result, ran_in)`` where ``ran_in`` is ``(channel, conv)``
        if the job ran inside an IM session, or ``None`` for isolated runs.
        Returns ``None`` outright if no target is available and the tick must
        be skipped.
        """
        if job.session_mode == "isolated":
            result = await self._executor.run_isolated(job.prompt)
            return (result, None)

        if job.session_mode == "main":
            target = self._executor._router.get_last_active_session()
            if target is None:
                return None
            channel_name, conv = target
            result = await self._executor.run_in_session(channel_name, conv, job.prompt)
            return (result, (channel_name, conv))

        if job.session_mode == "current":
            if not job.bound_channel or not job.bound_conversation_id:
                logger.warning("Cron job %s mode=current missing bound session; skipping", job.id)
                return None
            result = await self._executor.run_in_session(
                job.bound_channel, job.bound_conversation_id, job.prompt
            )
            return (result, (job.bound_channel, job.bound_conversation_id))

        logger.warning("Cron job %s has unknown session_mode %r", job.id, job.session_mode)
        return None

    async def _deliver(self, job: CronJob, result: str, ran_in: tuple[str, str] | None) -> None:
        label = job.name or job.id
        text = f"[Cron: {label}] {result}"
        delivery = job.delivery or "auto"

        if delivery == "none":
            return

        if delivery == "broadcast":
            await self._executor.broadcast(text)
            return

        if delivery.startswith("announce:"):
            _, ch_name, conv = delivery.split(":", 2)
            await self._executor.send_to(ch_name, conv, text)
            return

        # "auto": follow the session mode
        if ran_in is None:
            await self._executor.broadcast(text)
            return
        ch_name, conv = ran_in
        await self._executor.send_to(ch_name, conv, text)

    # ---- Persistence -------------------------------------------------------

    def _compute_next_run(self, job: CronJob) -> None:
        now = datetime.now(tz=timezone.utc)
        try:
            if job.schedule_type == "once":
                job.next_run_at = job.schedule_value
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
        os.makedirs(_BOT_DIR, exist_ok=True)
        data = [asdict(j) for j in self._jobs]
        try:
            with open(_CRON_JOBS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            logger.warning("Failed to save cron jobs", exc_info=True)

    def _load_jobs(self) -> None:
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
    from datetime import timedelta

    return timedelta(seconds=seconds)
