"""Tests for the manage_cron tool (CronTool)."""

from __future__ import annotations

from unittest.mock import MagicMock

from ouro.capabilities.tools.builtins.cron_tool import CronTool
from ouro.interfaces.bot.proactive import CronScheduler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scheduler(tmp_path, monkeypatch) -> CronScheduler:
    """Build a CronScheduler with isolated file storage."""
    monkeypatch.setattr(
        "ouro.interfaces.bot.proactive._CRON_JOBS_FILE", str(tmp_path / "cron_jobs.json")
    )
    monkeypatch.setattr("ouro.interfaces.bot.proactive._BOT_DIR", str(tmp_path))
    executor = MagicMock()
    return CronScheduler(executor)


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


class TestCronToolAdd:
    async def test_add_creates_job(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        result = await tool.execute(
            operation="add",
            schedule="300",
            prompt="Say hello",
            name="greeting",
        )

        assert "Created cron job" in result
        assert "greeting" in result
        assert "every=300" in result
        assert "session=main" in result
        assert "next_run=" in result
        assert len(sched.jobs) == 1
        # Default session_mode for the tool is "main".
        assert sched.jobs[0].session_mode == "main"

    async def test_add_isolated_mode(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        result = await tool.execute(
            operation="add",
            schedule="300",
            prompt="Broadcast",
            session_mode="isolated",
        )

        assert "session=isolated" in result
        assert sched.jobs[0].session_mode == "isolated"

    async def test_add_rejects_current_mode(self, tmp_path, monkeypatch):
        """The tool does not expose 'current' — only /cron add supports it."""
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        result = await tool.execute(
            operation="add",
            schedule="300",
            prompt="x",
            session_mode="current",
        )

        assert "Error" in result
        assert "not supported" in result
        assert len(sched.jobs) == 0

    async def test_add_cron_expression(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        result = await tool.execute(
            operation="add",
            schedule="0 9 * * *",
            prompt="Morning report",
        )

        assert "Created cron job" in result
        assert "cron=0 9 * * *" in result
        assert len(sched.jobs) == 1

    async def test_add_once_iso_datetime(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        result = await tool.execute(
            operation="add",
            schedule="2026-06-15T15:00:00+08:00",
            prompt="Remind me about the meeting",
            name="meeting-reminder",
        )

        assert "Created cron job" in result
        assert "meeting-reminder" in result
        assert "once=" in result
        assert len(sched.jobs) == 1
        assert sched.jobs[0].schedule_type == "once"

    async def test_add_missing_schedule(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        result = await tool.execute(operation="add", prompt="test")

        assert "Error" in result
        assert "schedule" in result
        assert len(sched.jobs) == 0

    async def test_add_missing_prompt(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        result = await tool.execute(operation="add", schedule="300")

        assert "Error" in result
        assert "prompt" in result
        assert len(sched.jobs) == 0

    async def test_add_invalid_schedule(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        result = await tool.execute(
            operation="add",
            schedule="bad cron expr",
            prompt="test",
        )

        assert "Error" in result
        assert "Invalid schedule" in result
        assert len(sched.jobs) == 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestCronToolList:
    async def test_list_empty(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        result = await tool.execute(operation="list")

        assert "No cron jobs" in result

    async def test_list_with_jobs(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        sched.add_job("300", "Say hello", name="greet")
        sched.add_job("0 9 * * *", "Morning report", name="report")

        result = await tool.execute(operation="list")

        assert "Cron jobs:" in result
        assert "greet" in result
        assert "report" in result
        assert "every=300" in result
        assert "cron=0 9 * * *" in result
        assert "enabled" in result


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


class TestCronToolRemove:
    async def test_remove_existing(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        job = sched.add_job("300", "test")

        result = await tool.execute(operation="remove", job_id=job.id)

        assert "Removed" in result
        assert job.id in result
        assert len(sched.jobs) == 0

    async def test_remove_nonexistent(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        result = await tool.execute(operation="remove", job_id="nonexistent")

        assert "Error" in result
        assert "nonexistent" in result

    async def test_remove_missing_job_id(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        result = await tool.execute(operation="remove")

        assert "Error" in result
        assert "job_id" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestCronToolEdgeCases:
    async def test_unknown_operation(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)

        result = await tool.execute(operation="unknown")

        assert "Error" in result
        assert "Unknown operation" in result

    def test_tool_name(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)
        assert tool.name == "manage_cron"

    def test_tool_schema(self, tmp_path, monkeypatch):
        sched = _make_scheduler(tmp_path, monkeypatch)
        tool = CronTool(sched)
        schema = tool.to_anthropic_schema()
        assert schema["name"] == "manage_cron"
        assert "operation" in schema["input_schema"]["properties"]
        assert "operation" in schema["input_schema"]["required"]
        # Optional params should NOT be in required
        assert "schedule" not in schema["input_schema"]["required"]
        assert "job_id" not in schema["input_schema"]["required"]
        assert "session_mode" not in schema["input_schema"]["required"]
        assert "session_mode" in schema["input_schema"]["properties"]
