"""Shell command execution tool."""

import asyncio
from typing import Any, Dict

from .base import BaseTool


class ShellTool(BaseTool):
    """Execute shell commands with a synchronous timeout."""

    DEFAULT_TIMEOUT = 120.0  # Default timeout in seconds
    MAX_TIMEOUT = 600.0  # Maximum allowed timeout

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return (
            "Execute shell commands. Returns stdout/stderr. "
            "Commands that exceed the timeout are killed and an error is returned."
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
                    "Timeout in seconds. Default is 120 seconds, maximum is 600 seconds."
                ),
                "default": 120.0,
            },
        }

    async def execute(self, command: str, timeout: float = 120.0) -> str:
        """Execute shell command and return output.

        Args:
            command: Shell command to execute
            timeout: Timeout in seconds (default: 120, max: 600)

        Returns:
            Command output or error message
        """
        actual_timeout = min(max(timeout, 1.0), self.MAX_TIMEOUT)

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=actual_timeout
                )
            except TimeoutError:
                process.kill()
                await process.communicate()
                return f"Error: Command timed out after {actual_timeout} seconds"

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
