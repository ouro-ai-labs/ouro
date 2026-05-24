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

    def tool_blocked(self, name: str, arguments: dict[str, Any], reason: str) -> None:
        terminal_ui.print_tool_blocked(name, arguments, reason)

    def final_answer(self, text: str) -> None:
        # The interactive shell renders the returned final answer itself;
        # no additional marker is needed.
        pass

    def unfinished_answer(self, text: str) -> None:
        terminal_ui.print_unfinished_answer(text)

    def spinner(self, label: str, title: str | None = None) -> AbstractAsyncContextManager[Any]:
        return AsyncSpinner(terminal_ui.console, label, title=title or "Working")

    def on_session_loaded(self, messages: list[Any]) -> None:
        """Replay persisted session messages using the same TUI renderers as live turns."""
        import json

        from ouro.interfaces.tui.theme import Theme

        if not messages:
            return

        colors = Theme.get_colors()
        terminal_ui.console.print(
            f"[bold {colors.primary}]Session History:[/bold {colors.primary}]"
        )
        terminal_ui.console.print(f"[{colors.text_muted}]{'─' * 60}[/{colors.text_muted}]")

        for msg in messages:
            role = getattr(msg, "role", None)
            if role == "user":
                terminal_ui.print_user_message(str(getattr(msg, "content", "") or ""))
            elif role == "assistant":
                content = getattr(msg, "content", None)
                if content:
                    terminal_ui.print_assistant_message(content)
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            fn = tc.get("function", {})
                            name = fn.get("name", "?")
                            try:
                                arguments = json.loads(fn.get("arguments", "{}"))
                            except json.JSONDecodeError:
                                arguments = {}
                        else:
                            name = getattr(getattr(tc, "function", None), "name", "?")
                            raw_args = getattr(getattr(tc, "function", None), "arguments", "{}")
                            try:
                                arguments = (
                                    json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                                )
                            except json.JSONDecodeError:
                                arguments = {}
                        terminal_ui.print_tool_call(name, arguments)
            elif role == "tool":
                terminal_ui.print_tool_result(str(getattr(msg, "content", "") or ""))

        terminal_ui.console.print(f"\n[{colors.text_muted}]{'─' * 60}[/{colors.text_muted}]\n")
