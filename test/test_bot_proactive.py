"""Tests for bot proactive mechanisms (heartbeat + cron)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.channel.base import OutgoingMessage
from bot.proactive import (
    CronScheduler,
    HeartbeatScheduler,
    IsolatedAgentRunner,
    _has_meaningful_content,
    load_heartbeat,
)
from bot.session_router import SessionRouter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeChannel:
    """Minimal channel for testing broadcasts."""

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
) -> IsolatedAgentRunner:
    """Build an IsolatedAgentRunner with mock agent and optional test sessions."""
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=agent_result)
    factory = lambda: mock_agent  # noqa: E731

    if channels is None:
        channels = [FakeChannel("test")]

    if router is None:
        router = SessionRouter(agent_factory=factory)
        # Pre-populate sessions if requested
        if sessions:
            for ch, cid in sessions:
                key = router._session_key(ch, cid)
                router._sessions[key] = MagicMock()
                router._last_active[key] = 0.0

    return IsolatedAgentRunner(factory, channels, router)


# ---------------------------------------------------------------------------
# load_heartbeat
# ---------------------------------------------------------------------------


class TestHasMeaningfulContent:
    def test_empty_string(self):
        assert _has_meaningful_content("") is False

    def test_only_headers(self):
        text = "# Heartbeat\n\n## Section\n"
        assert _has_meaningful_content(text) is False

    def test_header_without_space_is_content(self):
        """'#hashtag' is not a valid ATX header — treated as content."""
        assert _has_meaningful_content("#hashtag") is True

    def test_with_body_text(self):
        text = "# Heartbeat\n\nCheck disk space every hour.\n"
        assert _has_meaningful_content(text) is True

    def test_with_checklist(self):
        text = "# Heartbeat\n\n- [ ] Check disk space\n"
        assert _has_meaningful_content(text) is True

    def test_empty_checklist_items_skipped(self):
        text = "# Heartbeat\n\n- [ ]\n- \n* [ ]\n"
        assert _has_meaningful_content(text) is False

    def test_only_blank_lines(self):
        text = "\n\n\n"
        assert _has_meaningful_content(text) is False

    def test_default_template_skipped(self):
        from bot.proactive import _DEFAULT_HEARTBEAT

        assert _has_meaningful_content(_DEFAULT_HEARTBEAT) is False


class TestLoadHeartbeat:
    def test_creates_default_file(self, tmp_path, monkeypatch):
        hb_file = tmp_path / "heartbeat.md"
        monkeypatch.setattr("bot.proactive._HEARTBEAT_FILE", str(hb_file))
        monkeypatch.setattr("bot.proactive._BOT_DIR", str(tmp_path))
        content = load_heartbeat()
        assert hb_file.exists()
        assert "Heartbeat" in content

    def test_reads_existing_file(self, tmp_path, monkeypatch):
        hb_file = tmp_path / "heartbeat.md"
        hb_file.write_text("- Check servers")
        monkeypatch.setattr("bot.proactive._HEARTBEAT_FILE", str(hb_file))
        content = load_heartbeat()
        assert content == "- Check servers"


# ---------------------------------------------------------------------------
# IsolatedAgentRunner
# ---------------------------------------------------------------------------


class TestIsolatedAgentRunner:
    async def test_run_isolated_returns_agent_result(self):
        executor = _make_executor("hello world")
        result = await executor.run_isolated("test prompt")
        assert result == "hello world"

    async def test_run_isolated_timeout(self):
        """Agent exceeding timeout returns a timeout message."""
        mock_agent = MagicMock()

        async def slow_run(prompt):
            await asyncio.sleep(10)
            return "late"

        mock_agent.run = slow_run
        executor = IsolatedAgentRunner(lambda: mock_agent, [], SessionRouter(lambda: MagicMock()))

        with patch("bot.proactive._ISOLATED_TIMEOUT", 0.1):
            result = await executor.run_isolated("test")
        assert "timed out" in result

    async def test_broadcast_sends_to_active_sessions(self):
        ch = FakeChannel("test")
        executor = _make_executor(channels=[ch], sessions=[("test", "c1"), ("test", "c2")])
        count = await executor.broadcast("hello")
        assert count == 2
        assert len(ch.sent) == 2
        assert ch.sent[0].text == "hello"

    async def test_broadcast_no_sessions(self):
        executor = _make_executor()
        count = await executor.broadcast("hello")
        assert count == 0


# ---------------------------------------------------------------------------
# HeartbeatScheduler
# ---------------------------------------------------------------------------


def _make_heartbeat_scheduler(
    agent_result: str = "HEARTBEAT_OK",
    *,
    interval: int = 10,
    has_session: bool = True,
) -> tuple[HeartbeatScheduler, FakeChannel, MagicMock]:
    """Build a HeartbeatScheduler with a mock router/agent for testing."""
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=agent_result)
    factory = lambda: mock_agent  # noqa: E731

    ch = FakeChannel("test")
    router = SessionRouter(agent_factory=factory)

    if has_session:
        key = router._session_key("test", "c1")
        router._sessions[key] = mock_agent
        router._last_active[key] = 1.0

    scheduler = HeartbeatScheduler(router=router, channels=[ch], interval=interval)
    return scheduler, ch, mock_agent


class TestHeartbeatScheduler:
    async def test_heartbeat_ok_silently_dropped(self):
        scheduler, ch, _agent = _make_heartbeat_scheduler("HEARTBEAT_OK")

        with patch("bot.proactive.load_heartbeat", return_value="Check disk space daily"):
            await scheduler._tick()

        assert len(ch.sent) == 0

    async def test_heartbeat_skips_no_content(self):
        """No agent call when the heartbeat file has no meaningful content."""
        scheduler, ch, mock_agent = _make_heartbeat_scheduler()

        with patch("bot.proactive.load_heartbeat", return_value="# Heartbeat\n\n"):
            await scheduler._tick()

        mock_agent.run.assert_not_awaited()
        assert len(ch.sent) == 0

    async def test_heartbeat_skips_no_active_session(self):
        """No agent call when there are no active sessions."""
        scheduler, ch, mock_agent = _make_heartbeat_scheduler(has_session=False)

        with patch("bot.proactive.load_heartbeat", return_value="Check servers"):
            await scheduler._tick()

        mock_agent.run.assert_not_awaited()
        assert len(ch.sent) == 0

    async def test_heartbeat_sends_to_last_active(self):
        scheduler, ch, _agent = _make_heartbeat_scheduler("Server disk is 95% full")

        with patch("bot.proactive.load_heartbeat", return_value="Check disk space"):
            await scheduler._tick()

        assert len(ch.sent) == 1
        assert "[Heartbeat]" in ch.sent[0].text
        assert "disk" in ch.sent[0].text

    async def test_heartbeat_exception_does_not_crash(self):
        scheduler, ch, mock_agent = _make_heartbeat_scheduler()
        mock_agent.run = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("bot.proactive.load_heartbeat", return_value="Check servers"):
            # Should not raise
            await scheduler._tick()

    def test_disabled_when_interval_zero(self):
        scheduler, _, _ = _make_heartbeat_scheduler(interval=0)
        assert scheduler.enabled is False

    def test_enabled_when_interval_positive(self):
        scheduler, _, _ = _make_heartbeat_scheduler(interval=60)
        assert scheduler.enabled is True


# ---------------------------------------------------------------------------
# CronScheduler
# ---------------------------------------------------------------------------


class TestCronScheduler:
    @pytest.fixture(autouse=True)
    def _isolate_cron_files(self, tmp_path, monkeypatch):
        """Ensure each test uses an isolated cron jobs file."""
        monkeypatch.setattr("bot.proactive._CRON_JOBS_FILE", str(tmp_path / "cron_jobs.json"))
        monkeypatch.setattr("bot.proactive._BOT_DIR", str(tmp_path))

    def test_add_job_every(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        job = sched.add_job("300", "Say hello")
        assert job.schedule_type == "every"
        assert job.schedule_value == "300"
        assert job.next_run_at is not None

    def test_add_job_cron(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        job = sched.add_job("0 9 * * *", "Morning report")
        assert job.schedule_type == "cron"
        assert job.schedule_value == "0 9 * * *"

    def test_add_job_invalid_cron(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        with pytest.raises((ValueError, KeyError)):
            sched.add_job("bad cron expr", "test")

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

    async def test_tick_executes_due_job(self):
        executor = _make_executor("Job done")
        executor.broadcast = AsyncMock(return_value=1)
        sched = CronScheduler(executor)
        job = sched.add_job("300", "Do stuff", name="test-job")

        # Force the job to be due now
        past = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        job.next_run_at = past

        await sched._tick()

        executor.broadcast.assert_awaited_once()
        call_text = executor.broadcast.call_args[0][0]
        assert "[Cron: test-job]" in call_text
        # next_run_at should have been recomputed
        assert job.next_run_at != past

    async def test_tick_not_due_yet(self):
        executor = _make_executor()
        executor.run_isolated = AsyncMock()
        sched = CronScheduler(executor)
        sched.add_job("300", "test")
        # next_run_at is already in the future from add_job

        await sched._tick()

        executor.run_isolated.assert_not_awaited()

    def test_persistence_roundtrip(self, tmp_path):
        jobs_file = tmp_path / "cron_jobs.json"
        # Already patched by _isolate_cron_files, but the roundtrip test
        # needs to know the exact file to verify on disk.

        executor = _make_executor()
        sched = CronScheduler(executor)
        sched.add_job("600", "Persist me", name="persist-test")

        assert jobs_file.exists()
        data = json.loads(jobs_file.read_text())
        assert len(data) == 1
        assert data[0]["name"] == "persist-test"

        # Reload
        sched2 = CronScheduler(executor)
        assert len(sched2.jobs) == 1
        assert sched2.jobs[0].name == "persist-test"

    def test_add_job_once_iso(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        job = sched.add_job("2026-06-15T10:00:00+08:00", "Remind me about meeting")
        assert job.schedule_type == "once"
        assert job.schedule_value == "2026-06-15T10:00:00+08:00"
        assert job.next_run_at == "2026-06-15T10:00:00+08:00"

    def test_add_job_once_naive_gets_utc(self):
        executor = _make_executor()
        sched = CronScheduler(executor)
        job = sched.add_job("2026-06-15T10:00:00", "Remind me")
        assert job.schedule_type == "once"
        assert "+00:00" in job.schedule_value

    async def test_tick_executes_and_removes_once_job(self):
        executor = _make_executor("Reminder sent")
        executor.broadcast = AsyncMock(return_value=1)
        sched = CronScheduler(executor)
        job = sched.add_job("2020-01-01T00:00:00+00:00", "Old reminder")
        assert job.schedule_type == "once"
        assert len(sched.jobs) == 1

        await sched._tick()

        executor.broadcast.assert_awaited_once()
        # Job should be auto-removed after execution
        assert len(sched.jobs) == 0

    async def test_once_job_not_due_stays(self):
        executor = _make_executor()
        executor.run_isolated = AsyncMock()
        sched = CronScheduler(executor)
        sched.add_job("2099-12-31T23:59:59+00:00", "Far future task")
        assert len(sched.jobs) == 1

        await sched._tick()

        executor.run_isolated.assert_not_awaited()
        assert len(sched.jobs) == 1

    async def test_job_failure_does_not_crash_loop(self):
        executor = _make_executor()
        executor.run_isolated = AsyncMock(side_effect=RuntimeError("LLM down"))
        executor.broadcast = AsyncMock()
        sched = CronScheduler(executor)
        job = sched.add_job("300", "test")
        job.next_run_at = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()

        # Should not raise
        await sched._tick()

        # last_run_at should still be set
        assert job.last_run_at is not None


# ---------------------------------------------------------------------------
# Slash commands in BotServer
# ---------------------------------------------------------------------------


class TestProactiveSlashCommands:
    """Test /heartbeat and /cron commands via BotServer."""

    @pytest.fixture(autouse=True)
    def _isolate_cron_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("bot.proactive._CRON_JOBS_FILE", str(tmp_path / "cron_jobs.json"))
        monkeypatch.setattr("bot.proactive._BOT_DIR", str(tmp_path))

    @pytest.fixture
    def setup(self):
        from bot.server import BotServer

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="ok")
        router = SessionRouter(agent_factory=lambda: mock_agent)

        ch = FakeChannel("test")
        executor = _make_executor(channels=[ch], router=router)
        hb = HeartbeatScheduler(router=router, channels=[ch], interval=1800)
        cron = CronScheduler(executor)

        server = BotServer(
            session_router=router,
            channels=[ch],
            heartbeat=hb,
            cron_scheduler=cron,
        )
        return server, ch, cron

    def _msg(self, text: str):
        from bot.channel.base import IncomingMessage

        return IncomingMessage(
            channel="test",
            conversation_id="c1",
            user_id="u1",
            text=text,
            message_id="m1",
        )

    async def test_heartbeat_command(self, setup):
        server, ch, _ = setup
        await server._process_message(ch, self._msg("/heartbeat"))
        assert len(ch.sent) == 1
        assert "Heartbeat: enabled" in ch.sent[0].text
        assert "1800s" in ch.sent[0].text

    async def test_cron_list_empty(self, setup):
        server, ch, _ = setup
        await server._process_message(ch, self._msg("/cron list"))
        assert "No cron jobs" in ch.sent[0].text

    async def test_cron_add_and_list(self, setup):
        server, ch, cron = setup
        await server._process_message(ch, self._msg("/cron add 120 Say hello"))
        assert "Added cron job" in ch.sent[0].text

        ch.sent.clear()
        await server._process_message(ch, self._msg("/cron list"))
        assert "every=120" in ch.sent[0].text

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

    async def test_help_includes_proactive_commands(self, setup):
        server, ch, _ = setup
        await server._process_message(ch, self._msg("/help"))
        text = ch.sent[0].text
        assert "/heartbeat" in text
        assert "/cron" in text
