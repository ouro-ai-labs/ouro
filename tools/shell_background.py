"""Background task management for shell command execution."""

import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from .base import BaseTool


class TaskStatus(Enum):
    """Status of a background task."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    """Represents a background shell task."""

    task_id: str
    command: str
    status: TaskStatus = TaskStatus.RUNNING
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    process: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)


class BackgroundTaskManager:
    """Manages background shell tasks with automatic cleanup."""

    MAX_TASKS = 100
    TASK_EXPIRY_SECONDS = 3600  # 1 hour

    _instance: Optional["BackgroundTaskManager"] = None
    _lock = asyncio.Lock()

    def __init__(self) -> None:
        """Initialize the task manager."""
        self._tasks: Dict[str, BackgroundTask] = {}
        self._monitor_tasks: Dict[str, asyncio.Task] = {}

    async def shutdown(self) -> None:
        """Best-effort shutdown to prevent leaking subprocess transports.

        This is primarily intended for tests and graceful teardown. It cancels
        any monitor tasks and awaits them so they can kill/wait subprocesses.
        """

        monitors = list(self._monitor_tasks.values())
        for monitor in monitors:
            monitor.cancel()

        # Await monitor completion so their cancellation cleanup runs.
        for monitor in monitors:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await monitor

        # As an extra safety net, ensure any still-attached processes are killed.
        for task in list(self._tasks.values()):
            proc = task.process
            if proc is None:
                continue
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                # Use communicate() to consume stdout/stderr pipes, preventing
                # transport leaks when the event loop closes.
                await asyncio.wait_for(proc.communicate(), timeout=1.0)
            # Explicitly close the transport to prevent warnings when GC runs
            # after the event loop is closed.
            with contextlib.suppress(Exception):
                if hasattr(proc, "_transport") and proc._transport:
                    proc._transport.close()
            task.process = None

    @classmethod
    def get_instance(cls) -> "BackgroundTaskManager":
        """Get the singleton instance of the task manager."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    async def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        if cls._instance is not None:
            await cls._instance.shutdown()
            cls._instance = None

    async def submit_task(
        self,
        command: str,
        process: asyncio.subprocess.Process,
        timeout: Optional[float] = None,
    ) -> str:
        """Submit a running process as a background task.

        Args:
            command: The command being executed
            process: The running subprocess
            timeout: Optional timeout for the background task (default: no timeout)

        Returns:
            Task ID for tracking
        """
        await self._cleanup_old_tasks()

        task_id = str(uuid.uuid4())[:8]
        task = BackgroundTask(
            task_id=task_id,
            command=command,
            process=process,
        )
        self._tasks[task_id] = task

        # Start monitoring the task
        monitor = asyncio.create_task(self._monitor_task(task_id, timeout))
        self._monitor_tasks[task_id] = monitor

        return task_id

    async def _monitor_task(self, task_id: str, timeout: Optional[float] = None) -> None:
        """Monitor a background task until completion.

        Args:
            task_id: The task to monitor
            timeout: Optional timeout in seconds
        """
        task = self._tasks.get(task_id)
        if not task or not task.process:
            return

        try:
            if timeout:
                stdout, stderr = await asyncio.wait_for(task.process.communicate(), timeout=timeout)
            else:
                stdout, stderr = await task.process.communicate()

            task.stdout = stdout.decode() if stdout else ""
            task.stderr = stderr.decode() if stderr else ""
            task.exit_code = task.process.returncode
            task.completed_at = time.time()

            if task.exit_code == 0:
                task.status = TaskStatus.COMPLETED
            else:
                task.status = TaskStatus.FAILED

        except asyncio.TimeoutError:
            task.status = TaskStatus.TIMEOUT
            task.completed_at = time.time()
            if task.process:
                task.process.kill()
                with contextlib.suppress(Exception):
                    await task.process.communicate()
                # Explicitly close the transport
                with contextlib.suppress(Exception):
                    if hasattr(task.process, "_transport") and task.process._transport:
                        task.process._transport.close()

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()
            if task.process:
                task.process.kill()
                # Use communicate() to consume stdout/stderr pipes, preventing
                # transport leaks when the event loop closes.
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(task.process.communicate(), timeout=1.0)
                # Explicitly close the transport
                with contextlib.suppress(Exception):
                    if hasattr(task.process, "_transport") and task.process._transport:
                        task.process._transport.close()
            # Re-raise to properly propagate cancellation
            raise

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.stderr = str(e)
            task.completed_at = time.time()

        finally:
            # Clear process reference
            task.process = None
            # Remove from monitor tasks
            self._monitor_tasks.pop(task_id, None)

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of a task.

        Args:
            task_id: The task ID to query

        Returns:
            Task status dict or None if not found
        """
        task = self._tasks.get(task_id)
        if not task:
            return None

        return {
            "task_id": task.task_id,
            "command": task.command,
            "status": task.status.value,
            "exit_code": task.exit_code,
            "created_at": task.created_at,
            "completed_at": task.completed_at,
            "has_output": bool(task.stdout or task.stderr),
        }

    def get_task_output(
        self, task_id: str, max_chars: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Get the output of a task.

        Args:
            task_id: The task ID to query
            max_chars: Optional maximum characters to return

        Returns:
            Task output dict or None if not found
        """
        task = self._tasks.get(task_id)
        if not task:
            return None

        stdout = task.stdout
        stderr = task.stderr

        if max_chars:
            if len(stdout) > max_chars:
                stdout = stdout[:max_chars] + f"\n... (truncated, {len(task.stdout)} total chars)"
            if len(stderr) > max_chars:
                stderr = stderr[:max_chars] + f"\n... (truncated, {len(task.stderr)} total chars)"

        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": task.exit_code,
        }

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task.

        Args:
            task_id: The task ID to cancel

        Returns:
            True if cancelled, False if not found or already completed
        """
        task = self._tasks.get(task_id)
        if not task:
            return False

        if task.status != TaskStatus.RUNNING:
            return False

        # Cancel the monitor task
        monitor = self._monitor_tasks.get(task_id)
        if monitor:
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor

        return True

    def list_tasks(self, include_completed: bool = True) -> list[Dict[str, Any]]:
        """List all tasks.

        Args:
            include_completed: Whether to include completed tasks

        Returns:
            List of task status dicts
        """
        tasks = []
        for task in self._tasks.values():
            if not include_completed and task.status != TaskStatus.RUNNING:
                continue
            status = self.get_task_status(task.task_id)
            if status:
                tasks.append(status)

        # Sort by created_at descending
        tasks.sort(key=lambda t: t["created_at"], reverse=True)
        return tasks

    async def _cleanup_old_tasks(self) -> None:
        """Remove old completed tasks to prevent memory growth."""
        now = time.time()
        to_remove = []

        for task_id, task in self._tasks.items():
            # Remove completed tasks older than expiry time
            if (
                task.status != TaskStatus.RUNNING
                and task.completed_at
                and (now - task.completed_at) > self.TASK_EXPIRY_SECONDS
            ):
                to_remove.append(task_id)

        # If we still have too many tasks, remove oldest completed ones
        if len(self._tasks) - len(to_remove) > self.MAX_TASKS:
            completed = [
                (tid, t)
                for tid, t in self._tasks.items()
                if t.status != TaskStatus.RUNNING and tid not in to_remove
            ]
            completed.sort(key=lambda x: x[1].completed_at or 0)
            excess = len(self._tasks) - len(to_remove) - self.MAX_TASKS
            for tid, _ in completed[:excess]:
                to_remove.append(tid)

        for task_id in to_remove:
            del self._tasks[task_id]


class ShellTaskStatusTool(BaseTool):
    """Tool for querying background shell task status."""

    def __init__(self, task_manager: Optional[BackgroundTaskManager] = None) -> None:
        """Initialize the tool.

        Args:
            task_manager: Optional task manager instance (uses singleton if not provided)
        """
        self._task_manager = task_manager

    @property
    def task_manager(self) -> BackgroundTaskManager:
        """Get the task manager instance."""
        if self._task_manager is None:
            self._task_manager = BackgroundTaskManager.get_instance()
        return self._task_manager

    @property
    def name(self) -> str:
        return "shell_task_status"

    @property
    def description(self) -> str:
        return (
            "Query status and output of background shell tasks. "
            "Operations: 'status' (get task status), 'output' (get task output), "
            "'list' (list all tasks), 'cancel' (cancel a running task)."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "operation": {
                "type": "string",
                "description": "Operation to perform: 'status', 'output', 'list', or 'cancel'",
                "enum": ["status", "output", "list", "cancel"],
            },
            "task_id": {
                "type": "string",
                "description": "Task ID (required for status, output, cancel operations)",
                "default": "",
            },
            "include_completed": {
                "type": "boolean",
                "description": "For 'list' operation: whether to include completed tasks",
                "default": True,
            },
        }

    async def execute(
        self,
        operation: str,
        task_id: str = "",
        include_completed: bool = True,
    ) -> str:
        """Execute the tool operation.

        Args:
            operation: The operation to perform
            task_id: Task ID for status/output/cancel operations
            include_completed: For list operation, whether to include completed tasks

        Returns:
            Operation result as string
        """
        if operation == "list":
            tasks = self.task_manager.list_tasks(include_completed=include_completed)
            if not tasks:
                return "No background tasks found."

            lines = ["Background tasks:"]
            for t in tasks:
                status_emoji = {
                    "running": "[RUNNING]",
                    "completed": "[DONE]",
                    "failed": "[FAILED]",
                    "timeout": "[TIMEOUT]",
                    "cancelled": "[CANCELLED]",
                }.get(t["status"], "[?]")

                cmd_preview = t["command"][:50] + "..." if len(t["command"]) > 50 else t["command"]
                lines.append(f"  {t['task_id']}: {status_emoji} {cmd_preview}")

            return "\n".join(lines)

        # Operations that require task_id
        if not task_id:
            return f"Error: task_id is required for '{operation}' operation"

        if operation == "status":
            status = self.task_manager.get_task_status(task_id)
            if not status:
                return f"Error: Task '{task_id}' not found"

            lines = [
                f"Task: {status['task_id']}",
                f"Command: {status['command']}",
                f"Status: {status['status']}",
            ]
            if status["exit_code"] is not None:
                lines.append(f"Exit code: {status['exit_code']}")
            if status["has_output"]:
                lines.append("Output available: yes (use 'output' operation to retrieve)")

            return "\n".join(lines)

        elif operation == "output":
            # Limit output to stay within token limits
            max_chars = self.MAX_TOKENS * self.CHARS_PER_TOKEN
            output = self.task_manager.get_task_output(task_id, max_chars=max_chars)
            if not output:
                return f"Error: Task '{task_id}' not found"

            lines = [f"Task: {output['task_id']} ({output['status']})"]

            if output["stdout"]:
                lines.append(f"\n=== STDOUT ===\n{output['stdout']}")
            if output["stderr"]:
                lines.append(f"\n=== STDERR ===\n{output['stderr']}")
            if not output["stdout"] and not output["stderr"]:
                lines.append("\n(no output)")

            if output["exit_code"] is not None:
                lines.append(f"\nExit code: {output['exit_code']}")

            return "\n".join(lines)

        elif operation == "cancel":
            cancelled = await self.task_manager.cancel_task(task_id)
            if cancelled:
                return f"Task '{task_id}' has been cancelled."
            else:
                status = self.task_manager.get_task_status(task_id)
                if not status:
                    return f"Error: Task '{task_id}' not found"
                return f"Cannot cancel task '{task_id}': status is '{status['status']}'"

        else:
            return f"Error: Unknown operation '{operation}'"
