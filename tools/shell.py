"""Shell command execution tool."""

import asyncio
from typing import Any, Dict

from .base import BaseTool


class ShellTool(BaseTool):
    """Execute shell commands. Use with caution!"""

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return "Execute shell commands. Use with caution! Returns stdout/stderr."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
            }
        }

    async def execute(self, command: str) -> str:
        """Execute shell command and return output."""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            except TimeoutError:
                process.kill()
                await process.communicate()
                return "Error: Command timed out after 30 seconds"

            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""
            output = stdout_text + stderr_text if stderr_text else stdout_text
            if not output:
                return "Command executed (no output)"

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
