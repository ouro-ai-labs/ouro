"""Shell command execution tool."""

import asyncio
from typing import Any, Dict

from ...prompts.attribution import get_commit_and_pr_instructions
from ..base import BaseTool


class ShellTool(BaseTool):
    """Execute shell commands with a synchronous timeout."""

    DEFAULT_TIMEOUT = 120.0  # Default timeout in seconds
    MAX_TIMEOUT = 600.0  # Maximum allowed timeout

    # Exit-code semantics for common commands.
    # Maps (command_base, exit_code) -> human-readable meaning.
    _EXIT_SEMANTICS: dict[tuple[str, int], str] = {
        ("grep", 1): "no matches found",
        ("rg", 1): "no matches found",
        ("find", 1): "no matches found",
        ("diff", 1): "files differ",
        ("git", 1): "no changes / nothing to do",
    }

    def __init__(self, attribution_enabled: bool = True) -> None:
        """Args:
        attribution_enabled: When True, the description carries the
            commit/PR attribution template so commits and PRs the model
            authors end with ouro's trailers. See ``prompts.attribution``.
        """
        self._attribution_enabled = attribution_enabled

    @classmethod
    def _command_base(cls, command: str) -> str | None:
        """Extract the base command name (first token, stripped of flags)."""
        if not command:
            return None
        first = command.strip().split(None, 1)[0]
        # Strip leading path, e.g. /usr/bin/grep -> grep
        return first.rsplit("/", 1)[-1]

    @classmethod
    def _explain_exit_code(cls, command: str, code: int) -> str | None:
        """Return a human-readable explanation for a non-zero exit code, if known."""
        if code == 0:
            return None
        base = cls._command_base(command)
        if base is None:
            return None
        return cls._EXIT_SEMANTICS.get((base, code))

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        base = (
            "Execute shell commands. Returns stdout/stderr. "
            "Commands that exceed the timeout are killed and an error is returned."
        )
        instructions = get_commit_and_pr_instructions(self._attribution_enabled)
        return f"{base}\n\n{instructions}" if instructions else base

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

            # Append exit-code explanation for known commands
            returncode = process.returncode
            if returncode is not None and returncode != 0:
                explanation = self._explain_exit_code(command, returncode)
                if explanation:
                    output = (
                        f"{output}\n[exit {returncode}: {explanation}]"
                        if output
                        else f"[exit {returncode}: {explanation}]"
                    )
                else:
                    output = f"{output}\n[exit {returncode}]" if output else f"[exit {returncode}]"

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
