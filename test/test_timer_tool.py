"""Tests for the TimerTool."""

import time

import pytest

from tools.timer import TimerTool


@pytest.fixture
def timer_tool():
    return TimerTool()


class TestTimerToolProperties:
    def test_name(self, timer_tool):
        assert timer_tool.name == "timer"

    def test_description(self, timer_tool):
        assert "timer" in timer_tool.description.lower()

    def test_parameters(self, timer_tool):
        params = timer_tool.parameters
        assert "mode" in params
        assert "value" in params
        assert "task" in params

    def test_schema(self, timer_tool):
        schema = timer_tool.to_anthropic_schema()
        assert schema["name"] == "timer"
        assert "mode" in schema["input_schema"]["properties"]


class TestTimerDelay:
    async def test_delay_returns_task(self, timer_tool):
        result = await timer_tool.execute(mode="delay", value="0", task="do something")
        assert "Timer triggered" in result
        assert "do something" in result

    async def test_delay_no_recurring_instruction(self, timer_tool):
        result = await timer_tool.execute(mode="delay", value="0", task="one-shot")
        assert "MUST call the timer tool again" not in result

    async def test_delay_waits(self, timer_tool):
        start = time.monotonic()
        await timer_tool.execute(mode="delay", value="0.1", task="test")
        elapsed = time.monotonic() - start
        assert elapsed >= 0.09

    async def test_delay_invalid_value(self, timer_tool):
        result = await timer_tool.execute(mode="delay", value="abc", task="test")
        assert "Error" in result

    async def test_delay_negative_value(self, timer_tool):
        result = await timer_tool.execute(mode="delay", value="-1", task="test")
        assert "Error" in result


class TestTimerInterval:
    async def test_interval_returns_task(self, timer_tool):
        result = await timer_tool.execute(mode="interval", value="0", task="repeat this")
        assert "Timer triggered" in result
        assert "repeat this" in result

    async def test_interval_includes_recurring_instruction(self, timer_tool):
        result = await timer_tool.execute(mode="interval", value="0", task="repeat this")
        assert "MUST call the timer tool again" in result
        assert 'mode="interval"' in result

    async def test_interval_invalid_value(self, timer_tool):
        result = await timer_tool.execute(mode="interval", value="abc", task="test")
        assert "Error" in result

    async def test_interval_negative_value(self, timer_tool):
        result = await timer_tool.execute(mode="interval", value="-1", task="test")
        assert "Error" in result


class TestTimerCron:
    async def test_cron_invalid_expression(self, timer_tool):
        result = await timer_tool.execute(mode="cron", value="not a cron", task="test")
        assert "Error" in result
        assert "invalid cron" in result

    async def test_cron_valid_expression(self, timer_tool):
        result = await timer_tool.execute(mode="cron", value="* * * * *", task="cron task")
        assert "Timer triggered" in result
        assert "cron task" in result

    async def test_cron_includes_recurring_instruction(self, timer_tool):
        result = await timer_tool.execute(mode="cron", value="* * * * *", task="cron task")
        assert "MUST call the timer tool again" in result
        assert 'mode="cron"' in result


class TestTimerUnknownMode:
    async def test_unknown_mode(self, timer_tool):
        result = await timer_tool.execute(mode="bogus", value="1", task="test")
        assert "Error" in result
        assert "unknown mode" in result
