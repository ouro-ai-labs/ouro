"""TUI-backed ProgressSink — wraps terminal_ui + AsyncSpinner for the loop.

This lives in the interfaces layer so the capabilities layer never has to
import terminal_ui directly. The CLI/TUI factory injects an instance into
`AgentBuilder.with_progress_sink(...)`; the bot factory may inject a
quieter variant (or none) instead.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any

from ouro.core.loop import ProgressEvent
from ouro.interfaces.tui import terminal_ui
from ouro.interfaces.tui.progress import AsyncSpinner


class TuiProgressSink:
    """ProgressSink that renders to the TUI via terminal_ui + AsyncSpinner."""

    def __init__(self) -> None:
        self._swarm_plan_lines: list[str] = []
        self._swarm_agents: list[str] = []
        self._swarm_assignments: dict[str, str] = {}
        self._swarm_header_lines: list[str] = []
        self._swarm_status_line: str | None = None

    def _format_source_prefix(self, event: ProgressEvent) -> str:
        agent_id = event.source.agent_id
        if not agent_id or agent_id == "root":
            return ""
        return f"[{agent_id}] "

    def emit(self, event: ProgressEvent) -> None:
        kind = event.kind
        payload = event.payload
        prefix = self._format_source_prefix(event)

        if kind == "info":
            message = payload.get("message")
            if isinstance(message, str) and message:
                terminal_ui.print_info(f"{prefix}{message}")
            return

        if kind == "thinking":
            text = payload.get("text")
            if isinstance(text, str) and text:
                terminal_ui.print_thinking(f"{prefix}{text}")
            return

        if kind == "assistant_message":
            content = payload.get("text", payload.get("content"))
            if content is not None:
                if isinstance(content, str):
                    content = f"{prefix}{content}"
                terminal_ui.print_assistant_message(content)
            return

        if kind == "tool_call":
            name = payload.get("name")
            arguments = payload.get("arguments")
            if isinstance(name, str) and isinstance(arguments, dict):
                terminal_ui.print_tool_call(f"{prefix}{name}", arguments)
            return

        if kind == "tool_result":
            result = payload.get("text")
            if isinstance(result, str):
                terminal_ui.print_tool_result(f"{prefix}{result}")
            return

        if kind == "tool_blocked":
            name = payload.get("name")
            arguments = payload.get("arguments")
            reason = payload.get("reason")
            if isinstance(name, str) and isinstance(arguments, dict) and isinstance(reason, str):
                terminal_ui.print_tool_blocked(f"{prefix}{name}", arguments, reason)
            return

        if kind == "final_answer":
            # The interactive shell renders the returned final answer itself;
            # no additional marker is needed.
            return

        if kind == "unfinished_answer":
            text = payload.get("text")
            if isinstance(text, str):
                terminal_ui.print_unfinished_answer(text)
            return

        if kind == "task_list":
            task_lines = payload.get("task_lines")
            summary = payload.get("summary")
            if not isinstance(task_lines, list) or not all(
                isinstance(line, str) for line in task_lines
            ):
                terminal_ui.print_info(f"[{kind}] {payload}")
                return
            terminal_ui.print_task_summary(task_lines, summary=summary)
            return

        if kind == "task_status":
            line = payload.get("line")
            summary = payload.get("summary")
            task_lines = [line] if isinstance(line, str) and line else []
            terminal_ui.print_task_summary(
                task_lines,
                summary=summary,
                title=payload.get("title", "Task Update"),
            )
            return

        if kind == "verification_status":
            status = payload.get("status")
            attempt = payload.get("attempt")
            max_attempts = payload.get("max_attempts")
            reason = payload.get("reason")
            if (
                all(isinstance(value, int) for value in (attempt, max_attempts))
                and isinstance(status, str)
                and isinstance(reason, str)
            ):
                prefix = "✓" if status == "passed" else "⟳"
                terminal_ui.print_info(
                    f"{prefix} Verification {status} (attempt {attempt}/{max_attempts}): {reason}"
                )
            return

        if kind == "swarm_reset":
            self._reset_swarm_state(keep_headers=bool(payload.get("keep_headers", False)))
            return

        if kind == "swarm_header":
            line = payload.get("line")
            if isinstance(line, str) and line:
                self._swarm_header_lines.append(line)
            self._render_swarm_runtime(payload.get("title", "Swarm"))
            return

        if kind == "swarm_plan_item":
            line = payload.get("line")
            if isinstance(line, str) and line:
                self._swarm_plan_lines.append(line)
            self._render_swarm_runtime(payload.get("title", "Swarm Plan"))
            return

        if kind == "swarm_agent":
            agent = payload.get("agent")
            if isinstance(agent, str) and agent and agent not in self._swarm_agents:
                self._swarm_agents.append(agent)
            self._render_swarm_runtime(payload.get("title", "Swarm"))
            return

        if kind == "swarm_assignment":
            agent = payload.get("agent")
            assignment = payload.get("assignment")
            if isinstance(agent, str) and agent and isinstance(assignment, str) and assignment:
                self._swarm_assignments[agent] = assignment
            self._render_swarm_runtime(payload.get("title", "Swarm"))
            return

        if kind == "swarm_status":
            line = payload.get("line")
            if isinstance(line, str) and line:
                self._swarm_status_line = line
            self._render_swarm_runtime(payload.get("title", "Swarm Status"))
            return

        terminal_ui.print_info(f"[{kind}] {payload}")

    def _reset_swarm_state(self, keep_headers: bool = False) -> None:
        self._swarm_plan_lines = []
        self._swarm_agents = []
        self._swarm_assignments = {}
        self._swarm_status_line = None
        if not keep_headers:
            self._swarm_header_lines = []

    def _render_swarm_runtime(self, title: str = "Swarm") -> None:
        lines: list[str] = []
        if self._swarm_header_lines:
            lines.extend(self._swarm_header_lines)
        if self._swarm_plan_lines:
            if lines:
                lines.append("")
            lines.append("Plan:")
            lines.extend(self._swarm_plan_lines)
        if self._swarm_agents:
            if lines:
                lines.append("")
            lines.append(f"Agents: {', '.join(self._swarm_agents)}")
        if self._swarm_assignments:
            if lines:
                lines.append("")
            lines.append("Assignments:")
            lines.extend(
                f"- {agent}: {self._swarm_assignments[agent]}"
                for agent in sorted(self._swarm_assignments)
            )
        if self._swarm_status_line:
            if lines:
                lines.append("")
            lines.append(self._swarm_status_line)
        terminal_ui.print_swarm_summary(lines, title=title)

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
                content = str(getattr(msg, "content", "") or "")
                if content.startswith("[Previous conversation summary]"):
                    summary = content.removeprefix("[Previous conversation summary]").lstrip("\n")
                    terminal_ui.print_compaction_summary(summary)
                else:
                    terminal_ui.print_user_message(content)
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
