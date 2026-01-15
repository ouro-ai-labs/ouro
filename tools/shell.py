"""Shell command execution tool."""

import subprocess
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

    def execute(self, command: str) -> str:
        """Execute shell command and return output."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout if result.stdout else result.stderr
            return output if output else "Command executed (no output)"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds"
        except Exception as e:
            return f"Error executing command: {str(e)}"
