"""Shell command execution tool."""

import asyncio
from typing import TYPE_CHECKING, Any, Dict, Optional

from .base import BaseTool

if TYPE_CHECKING:
    from .shell_background import BackgroundTaskManager


class ShellTool(BaseTool):
    """Execute shell commands with automatic background execution for long-running tasks."""

    DEFAULT_TIMEOUT = 10.0  # Default timeout before moving to background
    MAX_WAIT_TIMEOUT = 600.0  # Maximum timeout when wait_for_completion is True

    def __init__(self, task_manager: Optional["BackgroundTaskManager"] = None) -> None:
        """Initialize the shell tool.

        Args:
            task_manager: Optional background task manager for handling long-running commands.
                         If not provided, will use the singleton instance when needed.
        """
        self._task_manager = task_manager

    @property
    def task_manager(self) -> "BackgroundTaskManager":
        """Get the task manager instance."""
        if self._task_manager is None:
            from .shell_background import BackgroundTaskManager

            self._task_manager = BackgroundTaskManager.get_instance()
        return self._task_manager

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return (
            "Execute shell commands. Returns stdout/stderr. "
            "Commands that don't complete within the timeout are automatically "
            "moved to background execution, returning a task_id for status tracking. "
            "Use shell_task_status tool to check on background tasks."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
            },
            "timeout": {
                "type": "number",
                "description": (
                    "Timeout in seconds before moving to background execution. "
                    "Default is 10 seconds."
                ),
                "default": 10.0,
            },
            "wait_for_completion": {
                "type": "boolean",
                "description": (
                    "If true, wait up to 600 seconds for completion instead of "
                    "moving to background. Use for commands that must complete synchronously."
                ),
                "default": False,
            },
        }

    async def execute(
        self,
        command: str,
        timeout: float = 10.0,
        wait_for_completion: bool = False,
    ) -> str:
        """Execute shell command and return output.

        Args:
            command: Shell command to execute
            timeout: Timeout in seconds before moving to background (default: 10)
            wait_for_completion: If True, wait up to 600s instead of backgrounding

        Returns:
            Command output, or task_id info if moved to background
        """
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Determine actual timeout (minimum 1 second if not waiting for completion)
            actual_timeout = self.MAX_WAIT_TIMEOUT if wait_for_completion else max(timeout, 1.0)

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=actual_timeout
                )
            except TimeoutError:
                if wait_for_completion:
                    # Even with wait_for_completion, we hit max timeout
                    process.kill()
                    await process.communicate()
                    return (
                        f"Error: Command timed out after {self.MAX_WAIT_TIMEOUT} seconds "
                        "(even with wait_for_completion=True)"
                    )

                # Move to background execution
                task_id = await self.task_manager.submit_task(
                    command=command,
                    process=process,
                    timeout=self.MAX_WAIT_TIMEOUT,  # Background tasks get extended timeout
                )

                return (
                    f"Command is taking longer than {timeout}s and has been moved to background.\n"
                    f"Task ID: {task_id}\n"
                    f"Use shell_task_status tool with operation='status' or 'output' to check progress."
                )

            # Command completed within timeout
            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""
            output = stdout_text + stderr_text if stderr_text else stdout_text

            if not output:
                return "Command executed successfully (no output)"

            # Check output size
            estimated_tokens = len(output) // self.CHARS_PER_TOKEN
            if estimated_tokens > self.MAX_TOKENS:
                return (
                    f"Error: Command output (~{estimated_tokens} tokens) exceeds "
                    f"maximum allowed ({self.MAX_TOKENS}). Please pipe output through "
                    f"head/tail/grep, or redirect to a file and read specific portions."
                )

            return output

        except Exception as e:
            return f"Error executing command: {str(e)}"
