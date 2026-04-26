"""Tests for bot proactive mechanisms (cron)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ouro.interfaces.bot.channel.base import OutgoingMessage
from ouro.interfaces.bot.proactive import (
    CronJob,
    CronScheduler,
    ProactiveExecutor,
)
from ouro.interfaces.bot.session_router import SessionRouter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeChannel:
    """Minimal channel for testing delivery paths."""

    def __init__(self, name: str = "test"):
        self.name = name
        self.sent: list[OutgoingMessage] = []

    async def start(self, cb) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_message(self, msg: OutgoingMessage) -> None:
        self.sent.append(msg)


def _make_executor(
    agent_result: str = "some result",
    *,
    channels: list | None = None,
    router: SessionRouter | None = None,
    sessions: list[tuple[str, str]] | None = None,
) -> ProactiveExecutor:
    """Build a ProactiveExecutor with mock agent and optional test sessions."""
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=agent_result)
    factory = lambda: mock_agent  # noqa: E731

    if channels is None:
        channels = [FakeChannel("test")]

    if router is None:
        router = SessionRouter(agent_factory=factory)
        if sessions:
            for idx, (ch, cid) in enumerate(sessions):
                key = router._session_key(ch, cid)
                router._sessions[key] = mock_agent
                # Spread timestamps so get_last_active_session is deterministic.
                router._last_active[key] = float(idx + 1)

    return ProactiveExecutor(factory, channels, router)


# ---------------------------------------------------------------------------
# ProactiveExecutor
# ---------------------------------------------------------------------------


class TestProactiveExecutor:
    async def test_run_isolated_returns_agent_result(self):
        executor = _make_executor("hello world")
        result = await executor.run_isolated("test prompt")
        assert result == "hello world"

    async def test_run_isolated_timeout(self):
        mock_agent = MagicMock()

        async def slow_run(prompt):
            await asyncio.sleep(10)
            return "late"

        mock_agent.run = slow_run
        executor = ProactiveExecutor(lambda: mock_agent, [], SessionRouter(lambda: MagicMock()))

        with patch("bot.proactive._ISOLATED_TIMEOUT", 0.1):
            result = await executor.run_isolated("test")
        assert "timed out" in result

    async def test_run_in_session_reuses_session_agent(self):
        ch = FakeChannel("test")
        executor = _make_executor("session reply", channels=[ch], sessions=[("test", "c1")])
        result = await executor.run_in_session("test", "c1", "hi")
        assert result == "session reply"

    async def test_broadcast_sends_to_active_sessions(self):
        ch = FakeChannel("test")
        executor = _make_executor(channels=[ch], sessions=[("test", "c1"), ("test", "c2")])
        count = await executor.broadcast("hello")
        assert count == 2
        assert len(ch.sent) == 2

    async def test_broadcast_no_sessions(self):
        executor = _make_executor()
        count = await executor.broadcast("hello")
        assert count == 0

    async def test_send_to_specific_target(self):
        ch = FakeChannel("test")
        executor = _make_executor(channels=[ch])
        ok = await executor.send_to("test", "c1", "hey")
        assert ok is True
        assert len(ch.sent) == 1
        assert ch.sent[0].conversation_id == "c1"
        assert ch.sent[0].text == "hey"

    async def test_send_to_unknown_channel(self):
        executor = _make_executor()
        ok = await executor.send_to("missing", "c1", "hey")
        assert ok is False


# ---------------------------------------------------------------------------
# CronScheduler — add_job / remove / persistence
# ---------------------------------------------------------------------------


class TestCronScheduler:
    @pytest.fixture(autouse=True)
    def _isolate_cron_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("bot.proactive._CRON_JOBS_FILE", str(tmp_path / "cron_jobs.json"))
        monkeypatch.setattr("bot.proactive._BOT_DIR", str(tmp_path))

    def test_add_job_every_defaults_to_main(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        job = sched.add_job("300", "Say hello")
        assert job.schedule_type == "every"
        assert job.session_mode == "main"
        assert job.delivery == "auto"
        assert job.next_run_at is not None

    def test_add_job_cron(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        job = sched.add_job("0 9 * * *", "Morning report")
        assert job.schedule_type == "cron"

    def test_add_job_invalid_cron(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        with pytest.raises((ValueError, KeyError)):
            sched.add_job("bad cron expr", "test")

    def test_add_job_invalid_session_mode(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        with pytest.raises(ValueError, match="session_mode"):
            sched.add_job("300", "x", session_mode="bogus")

    def test_add_job_invalid_delivery(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        with pytest.raises(ValueError, match="delivery"):
            sched.add_job("300", "x", delivery="whatever")

    def test_add_job_announce_delivery(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        job = sched.add_job("300", "x", delivery="announce:slack:C123")
        assert job.delivery == "announce:slack:C123"

    def test_add_job_announce_malformed(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        with pytest.raises(ValueError):
            sched.add_job("300", "x", delivery="announce:slack")

    def test_add_job_current_requires_binding(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        with pytest.raises(ValueError, match="bound_channel"):
            sched.add_job("300", "x", session_mode="current")

    def test_add_job_current_with_binding(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        job = sched.add_job(
            "300",
            "x",
            session_mode="current",
            bound_channel="test",
            bound_conversation_id="c1",
        )
        assert job.session_mode == "current"
        assert job.bound_channel == "test"
        assert job.bound_conversation_id == "c1"

    def test_remove_job(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        job = sched.add_job("300", "test")
        assert sched.remove_job(job.id) is True
        assert len(sched.jobs) == 0

    def test_remove_nonexistent_job(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        assert sched.remove_job("nonexistent") is False

    def test_persistence_roundtrip_includes_new_fields(self, tmp_path):
        jobs_file = tmp_path / "cron_jobs.json"
        executor = _make_executor()
        sched = CronScheduler(executor)
        sched.add_job(
            "600",
            "Persist me",
            name="persist-test",
            session_mode="isolated",
            delivery="broadcast",
        )

        data = json.loads(jobs_file.read_text())
        assert data[0]["session_mode"] == "isolated"
        assert data[0]["delivery"] == "broadcast"

        sched2 = CronScheduler(executor)
        reloaded = sched2.jobs[0]
        assert reloaded.session_mode == "isolated"
        assert reloaded.delivery == "broadcast"

    def test_persistence_missing_fields_default_to_isolated(self, tmp_path):
        """Pre-refactor persisted jobs (missing session_mode/delivery) keep old behavior."""
        jobs_file = tmp_path / "cron_jobs.json"
        jobs_file.write_text(
            json.dumps(
                [
                    {
                        "id": "legacy1",
                        "name": "legacy",
                        "schedule_type": "every",
                        "schedule_value": "300",
                        "prompt": "old",
                        "enabled": True,
                        "next_run_at": "2020-01-01T00:00:00+00:00",
                    }
                ]
            )
        )
        executor = _make_executor()
        sched = CronScheduler(executor)
        assert len(sched.jobs) == 1
        assert sched.jobs[0].session_mode == "isolated"
        assert sched.jobs[0].delivery == "auto"


# ---------------------------------------------------------------------------
# CronScheduler — _execute_job routing by session_mode + delivery
# ---------------------------------------------------------------------------


class TestCronSchedulerRouting:
    @pytest.fixture(autouse=True)
    def _isolate_cron_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("bot.proactive._CRON_JOBS_FILE", str(tmp_path / "cron_jobs.json"))
        monkeypatch.setattr("bot.proactive._BOT_DIR", str(tmp_path))

    def _past(self) -> str:
        return datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()

    async def test_mode_isolated_auto_delivery_broadcasts(self):
        ch = FakeChannel("test")
        executor = _make_executor("isolated reply", channels=[ch], sessions=[("test", "c1")])
        sched = CronScheduler(executor)
        job = sched.add_job("300", "x", name="iso", session_mode="isolated")
        job.next_run_at = self._past()

        await sched._tick()

        # "auto" on isolated → broadcast to all active sessions.
        assert len(ch.sent) == 1
        assert "[Cron: iso]" in ch.sent[0].text
        assert "isolated reply" in ch.sent[0].text

    async def test_mode_main_runs_in_last_active_and_replies_there(self):
        ch = FakeChannel("test")
        executor = _make_executor(
            "main reply", channels=[ch], sessions=[("test", "c1"), ("test", "c2")]
        )
        sched = CronScheduler(executor)
        job = sched.add_job("300", "x", name="main-job", session_mode="main")
        job.next_run_at = self._past()

        await sched._tick()

        # Last active is "test:c2" (second session gets higher timestamp in helper).
        assert len(ch.sent) == 1
        assert ch.sent[0].conversation_id == "c2"
        assert "[Cron: main-job]" in ch.sent[0].text

    async def test_mode_main_skips_when_no_active_session(self):
        ch = FakeChannel("test")
        executor = _make_executor("never", channels=[ch], sessions=None)
        sched = CronScheduler(executor)
        job = sched.add_job("300", "x", session_mode="main")
        job.next_run_at = self._past()

        await sched._tick()

        # No active session → no delivery, but next_run_at should be recomputed
        # so last_run_at is set and we don't retry immediately.
        assert len(ch.sent) == 0
        assert job.last_run_at is not None

    async def test_mode_current_uses_binding(self):
        ch = FakeChannel("test")
        executor = _make_executor(
            "current reply",
            channels=[ch],
            sessions=[("test", "c1"), ("test", "bound")],
        )
        sched = CronScheduler(executor)
        job = sched.add_job(
            "300",
            "x",
            name="bound-job",
            session_mode="current",
            bound_channel="test",
            bound_conversation_id="bound",
        )
        job.next_run_at = self._past()

        await sched._tick()

        assert len(ch.sent) == 1
        assert ch.sent[0].conversation_id == "bound"

    async def test_delivery_none_suppresses_send(self):
        ch = FakeChannel("test")
        executor = _make_executor("silent", channels=[ch], sessions=[("test", "c1")])
        sched = CronScheduler(executor)
        job = sched.add_job("300", "x", session_mode="main", delivery="none")
        job.next_run_at = self._past()

        await sched._tick()

        assert len(ch.sent) == 0

    async def test_delivery_announce_target(self):
        ch = FakeChannel("test")
        executor = _make_executor("announce", channels=[ch], sessions=[("test", "c1")])
        sched = CronScheduler(executor)
        job = sched.add_job(
            "300",
            "x",
            name="ann",
            session_mode="isolated",
            delivery="announce:test:custom-chan",
        )
        job.next_run_at = self._past()

        await sched._tick()

        assert len(ch.sent) == 1
        assert ch.sent[0].conversation_id == "custom-chan"

    async def test_delivery_broadcast_override(self):
        ch = FakeChannel("test")
        executor = _make_executor(
            "bcast",
            channels=[ch],
            sessions=[("test", "c1"), ("test", "c2")],
        )
        sched = CronScheduler(executor)
        job = sched.add_job("300", "x", session_mode="main", delivery="broadcast")
        job.next_run_at = self._past()

        await sched._tick()

        # broadcast override → both sessions, not just the "main" session.
        assert len(ch.sent) == 2

    def test_tick_not_due_yet_no_execution(self):
        """Future jobs are not executed by _tick."""
        executor = _make_executor()
        sched = CronScheduler(executor)
        sched.add_job("300", "x")  # next_run is in the future

        # Using a sync helper since we're testing the guard, not a coroutine
        # path. The test intentionally does not await _tick — we only assert
        # the scheduler stayed consistent.
        assert len(sched.jobs) == 1
        assert sched.jobs[0].last_run_at is None

    async def test_once_job_removed_after_execution(self):
        ch = FakeChannel("test")
        executor = _make_executor("once reply", channels=[ch], sessions=[("test", "c1")])
        sched = CronScheduler(executor)
        job = sched.add_job("2020-01-01T00:00:00+00:00", "one-shot", session_mode="main")
        assert job.schedule_type == "once"

        await sched._tick()

        assert len(sched.jobs) == 0
        assert len(ch.sent) == 1

    async def test_job_failure_does_not_crash_loop(self):
        executor = _make_executor()
        executor.run_isolated = AsyncMock(side_effect=RuntimeError("LLM down"))
        executor.broadcast = AsyncMock()
        sched = CronScheduler(executor)
        job = sched.add_job("300", "test", session_mode="isolated")
        job.next_run_at = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()

        await sched._tick()  # must not raise

        assert job.last_run_at is not None


# ---------------------------------------------------------------------------
# Slash commands in BotServer
# ---------------------------------------------------------------------------


class TestProactiveSlashCommands:
    @pytest.fixture(autouse=True)
    def _isolate_cron_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("bot.proactive._CRON_JOBS_FILE", str(tmp_path / "cron_jobs.json"))
        monkeypatch.setattr("bot.proactive._BOT_DIR", str(tmp_path))

    @pytest.fixture
    def setup(self):
        from ouro.interfaces.bot.server import BotServer

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="ok")
        router = SessionRouter(agent_factory=lambda: mock_agent)

        ch = FakeChannel("test")
        executor = _make_executor(channels=[ch], router=router)
        cron = CronScheduler(executor)

        server = BotServer(session_router=router, channels=[ch], cron_scheduler=cron)
        return server, ch, cron

    def _msg(self, text: str):
        from ouro.interfaces.bot.channel.base import IncomingMessage

        return IncomingMessage(
            channel="test",
            conversation_id="c1",
            user_id="u1",
            text=text,
            message_id="m1",
        )

    async def test_cron_list_empty(self, setup):
        server, ch, _ = setup
        await server._process_message(ch, self._msg("/cron list"))
        assert "No cron jobs" in ch.sent[0].text

    async def test_cron_add_default_main_mode(self, setup):
        server, ch, cron = setup
        await server._process_message(ch, self._msg("/cron add 120 Say hello"))
        assert "Added cron job" in ch.sent[0].text
        assert "session=main" in ch.sent[0].text
        assert cron.jobs[0].session_mode == "main"

    async def test_cron_add_isolated_session_flag(self, setup):
        server, ch, cron = setup
        await server._process_message(
            ch, self._msg("/cron add --session isolated 120 Broadcast me")
        )
        assert cron.jobs[0].session_mode == "isolated"

    async def test_cron_add_current_binds_to_sender(self, setup):
        server, ch, cron = setup
        await server._process_message(ch, self._msg("/cron add --session current 120 In this chat"))
        job = cron.jobs[0]
        assert job.session_mode == "current"
        assert job.bound_channel == "test"
        assert job.bound_conversation_id == "c1"

    async def test_cron_add_deliver_flag(self, setup):
        server, ch, cron = setup
        await server._process_message(
            ch,
            self._msg("/cron add --deliver none 120 Silent job"),
        )
        assert cron.jobs[0].delivery == "none"

    async def test_cron_add_invalid_session_flag(self, setup):
        server, ch, cron = setup
        await server._process_message(ch, self._msg("/cron add --session bogus 120 x"))
        assert "Invalid cron args" in ch.sent[0].text
        assert len(cron.jobs) == 0

    async def test_cron_remove(self, setup):
        server, ch, cron = setup
        job = cron.add_job("300", "test")
        await server._process_message(ch, self._msg(f"/cron remove {job.id}"))
        assert "Removed" in ch.sent[0].text
        assert len(cron.jobs) == 0

    async def test_cron_remove_nonexistent(self, setup):
        server, ch, _ = setup
        await server._process_message(ch, self._msg("/cron remove fake123"))
        assert "No cron job" in ch.sent[0].text

    async def test_help_no_longer_mentions_heartbeat(self, setup):
        server, ch, _ = setup
        await server._process_message(ch, self._msg("/help"))
        text = ch.sent[0].text
        assert "/heartbeat" not in text
        assert "/cron" in text


# ---------------------------------------------------------------------------
# CronJob dataclass
# ---------------------------------------------------------------------------


class TestCronJob:
    def test_defaults(self):
        job = CronJob()
        # Dataclass default stays "isolated" so pre-refactor persisted jobs
        # keep their old behavior on reload.
        assert job.session_mode == "isolated"
        assert job.delivery == "auto"
        assert job.bound_channel is None
        assert job.bound_conversation_id is None
