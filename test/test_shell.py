"""Tests for simplified shell tool."""

import pytest

from tools.shell import ShellTool


class TestShellTool:
    """Tests for ShellTool."""

    @pytest.mark.asyncio
    async def test_quick_command_returns_output(self):
        """Test that a quick command returns its output."""
        tool = ShellTool()
        result = await tool.execute("echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_command_with_stderr(self):
        """Test command that produces stderr."""
        tool = ShellTool()
        result = await tool.execute("echo error >&2")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_output_message(self):
        """Test that commands with no output show appropriate message."""
        tool = ShellTool()
        result = await tool.execute("true")
        assert "no output" in result.lower()

    @pytest.mark.asyncio
    async def test_timeout_kills_and_returns_error(self):
        """Test that exceeding the timeout kills the process and returns error."""
        tool = ShellTool()
        result = await tool.execute("sleep 60", timeout=1.0)
        assert "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_timeout_clamped_to_max(self):
        """Test that timeout cannot exceed MAX_TIMEOUT."""
        tool = ShellTool()
        # Requesting a huge timeout should still work (clamped to MAX_TIMEOUT)
        result = await tool.execute("echo ok", timeout=99999.0)
        assert "ok" in result

    def test_tool_name(self):
        """Test tool name."""
        tool = ShellTool()
        assert tool.name == "shell"

    def test_tool_parameters_no_wait_for_completion(self):
        """Test that wait_for_completion parameter was removed."""
        tool = ShellTool()
        params = tool.parameters
        assert "command" in params
        assert "timeout" in params
        assert "wait_for_completion" not in params

    def test_default_timeout_is_120(self):
        """Test default timeout is 120 seconds."""
        assert ShellTool.DEFAULT_TIMEOUT == 120.0
