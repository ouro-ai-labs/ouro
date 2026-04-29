"""TUI-backed ProgressSink — wraps terminal_ui + AsyncSpinner for the loop.

This lives in the interfaces layer so the capabilities layer never has to
import terminal_ui directly. The CLI/TUI factory injects an instance into
`AgentBuilder.with_progress_sink(...)`; the bot factory may inject a
quieter variant (or none) instead.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any

from ouro.interfaces.tui import terminal_ui
from ouro.interfaces.tui.progress import AsyncSpinner


class TuiProgressSink:
    """ProgressSink that renders to the TUI via terminal_ui + AsyncSpinner."""

    def info(self, msg: str) -> None:
        if msg:
            terminal_ui.console.print(msg)

    def thinking(self, text: str) -> None:
        terminal_ui.print_thinking(text)

    def assistant_message(self, content: Any) -> None:
        terminal_ui.print_assistant_message(content)

    def tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        terminal_ui.print_tool_call(name, arguments)

    def tool_result(self, result: str) -> None:
        terminal_ui.print_tool_result(result)

    def final_answer(self, text: str) -> None:
        # The interactive shell renders the returned final answer itself; here
        # we only emit a lightweight completion marker for non-interactive
        # progress consumers.
        terminal_ui.console.print("\n[bold green]✓ Final answer received[/bold green]")

    def unfinished_answer(self, text: str) -> None:
        terminal_ui.print_unfinished_answer(text)

    def spinner(self, label: str, title: str | None = None) -> AbstractAsyncContextManager[Any]:
        return AsyncSpinner(terminal_ui.console, label, title=title or "Working")
