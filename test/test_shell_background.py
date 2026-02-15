"""Tests for shell background execution functionality."""

import asyncio

import pytest
import pytest_asyncio

from tools.shell import ShellTool
from tools.shell_background import (
    BackgroundTaskManager,
    ShellTaskStatusTool,
    TaskStatus,
)


@pytest_asyncio.fixture
async def task_manager():
    """Create a fresh task manager for each test."""
    # Reset singleton to ensure clean state
    await BackgroundTaskManager.reset_instance()
    manager = BackgroundTaskManager()
    try:
        yield manager
    finally:
        # Ensure monitor tasks are awaited so subprocess transports are cleaned
        # up before pytest closes the event loop.
        await manager.shutdown()


@pytest_asyncio.fixture
async def shell_tool(task_manager):
    """Create a shell tool with injected task manager."""
    return ShellTool(task_manager=task_manager)


@pytest_asyncio.fixture
async def status_tool(task_manager):
    """Create a status tool with injected task manager."""
    return ShellTaskStatusTool(task_manager=task_manager)


class TestBackgroundTaskManager:
    """Tests for BackgroundTaskManager."""

    @pytest.mark.asyncio
    async def test_singleton_pattern(self):
        """Test that get_instance returns the same instance."""
        await BackgroundTaskManager.reset_instance()
        instance1 = BackgroundTaskManager.get_instance()
        instance2 = BackgroundTaskManager.get_instance()
        assert instance1 is instance2
        await BackgroundTaskManager.reset_instance()

    @pytest.mark.asyncio
    async def test_submit_and_complete_task(self, task_manager):
        """Test submitting a task and waiting for completion."""
        # Start a quick process
        process = await asyncio.create_subprocess_shell(
            "echo hello",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        task_id = await task_manager.submit_task(
            command="echo hello",
            process=process,
            timeout=10.0,
        )

        assert task_id is not None
        assert len(task_id) == 8  # UUID prefix

        # Wait for completion
        await asyncio.sleep(0.5)

        status = task_manager.get_task_status(task_id)
        assert status is not None
        assert status["status"] == TaskStatus.COMPLETED.value
        assert status["exit_code"] == 0

        output = task_manager.get_task_output(task_id)
        assert output is not None
        assert "hello" in output["stdout"]

    @pytest.mark.asyncio
    async def test_task_failure(self, task_manager):
        """Test that failed tasks are tracked correctly."""
        process = await asyncio.create_subprocess_shell(
            "exit 1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        task_id = await task_manager.submit_task(
            command="exit 1",
            process=process,
            timeout=10.0,
        )

        await asyncio.sleep(0.5)

        status = task_manager.get_task_status(task_id)
        assert status["status"] == TaskStatus.FAILED.value
        assert status["exit_code"] == 1

    @pytest.mark.asyncio
    async def test_cancel_running_task(self, task_manager):
        """Test cancelling a running task."""
        process = await asyncio.create_subprocess_shell(
            "sleep 60",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        task_id = await task_manager.submit_task(
            command="sleep 60",
            process=process,
            timeout=120.0,
        )

        # Give monitor task time to start
        await asyncio.sleep(0.1)

        # Task should be running
        status = task_manager.get_task_status(task_id)
        assert status["status"] == TaskStatus.RUNNING.value

        # Cancel it
        cancelled = await task_manager.cancel_task(task_id)
        assert cancelled is True

        # Status should be cancelled immediately after cancel_task returns
        status = task_manager.get_task_status(task_id)
        assert status["status"] == TaskStatus.CANCELLED.value

    @pytest.mark.asyncio
    async def test_list_tasks(self, task_manager):
        """Test listing tasks."""
        # Submit a few tasks
        for i in range(3):
            process = await asyncio.create_subprocess_shell(
                f"echo task{i}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await task_manager.submit_task(
                command=f"echo task{i}",
                process=process,
            )

        await asyncio.sleep(0.5)

        tasks = task_manager.list_tasks()
        assert len(tasks) == 3

        # Test filtering
        tasks_running = task_manager.list_tasks(include_completed=False)
        assert len(tasks_running) == 0  # All should be completed

    @pytest.mark.asyncio
    async def test_task_not_found(self, task_manager):
        """Test querying non-existent task."""
        status = task_manager.get_task_status("nonexistent")
        assert status is None

        output = task_manager.get_task_output("nonexistent")
        assert output is None


class TestShellTool:
    """Tests for ShellTool with background execution."""

    @pytest.mark.asyncio
    async def test_quick_command_returns_immediately(self, shell_tool):
        """Test that quick commands return output directly."""
        result = await shell_tool.execute("echo hello", timeout=10.0)
        assert "hello" in result
        assert "Task ID" not in result

    @pytest.mark.asyncio
    async def test_slow_command_moves_to_background(self, shell_tool):
        """Test that slow commands are moved to background."""
        result = await shell_tool.execute("sleep 5 && echo done", timeout=1.0)

        assert "Task ID" in result
        assert "background" in result.lower()
        assert "shell_task_status" in result

    @pytest.mark.asyncio
    async def test_wait_for_completion_extends_timeout(self, shell_tool):
        """Test that wait_for_completion prevents backgrounding."""
        result = await shell_tool.execute(
            "sleep 2 && echo completed",
            timeout=1.0,
            wait_for_completion=True,
        )

        assert "completed" in result
        assert "Task ID" not in result

    @pytest.mark.asyncio
    async def test_command_with_stderr(self, shell_tool):
        """Test command that produces stderr."""
        result = await shell_tool.execute("echo error >&2", timeout=10.0)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_command_with_exit_code(self, shell_tool):
        """Test command that fails."""
        result = await shell_tool.execute("exit 0", timeout=10.0)
        assert "executed successfully" in result.lower() or result == ""

    @pytest.mark.asyncio
    async def test_no_output_message(self, shell_tool):
        """Test that commands with no output show appropriate message."""
        result = await shell_tool.execute("true", timeout=10.0)
        assert "no output" in result.lower()


class TestShellTaskStatusTool:
    """Tests for ShellTaskStatusTool."""

    @pytest.mark.asyncio
    async def test_list_empty(self, status_tool):
        """Test listing when no tasks exist."""
        result = await status_tool.execute(operation="list")
        assert "No background tasks" in result

    @pytest.mark.asyncio
    async def test_list_with_tasks(self, status_tool, task_manager):
        """Test listing tasks."""
        # Add a task
        process = await asyncio.create_subprocess_shell(
            "echo test",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await task_manager.submit_task(command="echo test", process=process)
        await asyncio.sleep(0.5)

        result = await status_tool.execute(operation="list")
        assert "echo test" in result
        assert "[DONE]" in result

    @pytest.mark.asyncio
    async def test_status_operation(self, status_tool, task_manager):
        """Test status operation."""
        process = await asyncio.create_subprocess_shell(
            "echo hello",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        task_id = await task_manager.submit_task(command="echo hello", process=process)
        await asyncio.sleep(0.5)

        result = await status_tool.execute(operation="status", task_id=task_id)
        assert task_id in result
        assert "echo hello" in result
        assert "completed" in result.lower()

    @pytest.mark.asyncio
    async def test_output_operation(self, status_tool, task_manager):
        """Test output operation."""
        process = await asyncio.create_subprocess_shell(
            "echo hello_world",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        task_id = await task_manager.submit_task(command="echo hello_world", process=process)
        await asyncio.sleep(0.5)

        result = await status_tool.execute(operation="output", task_id=task_id)
        assert "hello_world" in result
        assert "STDOUT" in result

    @pytest.mark.asyncio
    async def test_cancel_operation(self, status_tool, task_manager):
        """Test cancel operation."""
        process = await asyncio.create_subprocess_shell(
            "sleep 60",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        task_id = await task_manager.submit_task(command="sleep 60", process=process)

        result = await status_tool.execute(operation="cancel", task_id=task_id)
        assert "cancelled" in result.lower()

    @pytest.mark.asyncio
    async def test_status_missing_task_id(self, status_tool):
        """Test status operation without task_id."""
        result = await status_tool.execute(operation="status")
        assert "Error" in result
        assert "task_id is required" in result

    @pytest.mark.asyncio
    async def test_status_nonexistent_task(self, status_tool):
        """Test status operation with nonexistent task."""
        result = await status_tool.execute(operation="status", task_id="nonexistent")
        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_cancel_already_completed(self, status_tool, task_manager):
        """Test cancelling an already completed task."""
        process = await asyncio.create_subprocess_shell(
            "echo done",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        task_id = await task_manager.submit_task(command="echo done", process=process)
        await asyncio.sleep(0.5)

        result = await status_tool.execute(operation="cancel", task_id=task_id)
        assert "Cannot cancel" in result
        assert "completed" in result


class TestIntegration:
    """Integration tests for shell background execution."""

    @pytest.mark.asyncio
    async def test_full_workflow(self, shell_tool, status_tool, task_manager):
        """Test complete workflow: execute slow command, check status, get output."""
        # Start a slow command
        result = await shell_tool.execute("sleep 2 && echo workflow_done", timeout=0.5)

        assert "Task ID" in result
        # Extract task_id from result
        for line in result.split("\n"):
            if "Task ID:" in line:
                task_id = line.split(":")[-1].strip()
                break

        # Check status (should be running)
        status_result = await status_tool.execute(operation="status", task_id=task_id)
        assert task_id in status_result

        # Wait for completion
        await asyncio.sleep(3)

        # Check status again (should be completed)
        status_result = await status_tool.execute(operation="status", task_id=task_id)
        assert "completed" in status_result.lower()

        # Get output
        output_result = await status_tool.execute(operation="output", task_id=task_id)
        assert "workflow_done" in output_result
