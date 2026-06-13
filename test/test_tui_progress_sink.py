from __future__ import annotations

from ouro.core.loop import EventSource, ProgressEvent
from ouro.interfaces.tui.tui_progress import TuiProgressSink


def test_emit_renders_task_list_with_summary(monkeypatch):
    calls: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        "ouro.interfaces.tui.tui_progress.terminal_ui.print_task_summary",
        lambda task_lines, summary=None, title="Tasks": calls.append((task_lines, summary)),
    )

    sink = TuiProgressSink()
    sink.emit(
        ProgressEvent(
            kind="task_list",
            payload={
                "task_lines": ["[pending] #1 Task A", "[running] #2 Task B"],
                "summary": "Summary: 0 done, 1 running, 0 blocked, 1 pending",
            },
        )
    )

    assert calls == [
        (
            ["[pending] #1 Task A", "[running] #2 Task B"],
            "Summary: 0 done, 1 running, 0 blocked, 1 pending",
        )
    ]


def test_emit_falls_back_for_invalid_task_list_payload(monkeypatch):
    infos: list[str] = []
    calls: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        "ouro.interfaces.tui.tui_progress.terminal_ui.print_info",
        lambda msg: infos.append(msg),
    )
    monkeypatch.setattr(
        "ouro.interfaces.tui.tui_progress.terminal_ui.print_task_summary",
        lambda task_lines, summary=None, title="Tasks": calls.append((task_lines, summary)),
    )

    sink = TuiProgressSink()
    sink.emit(ProgressEvent(kind="task_list", payload={"task_lines": "oops", "summary": "bad"}))

    assert calls == []
    assert infos == ["[task_list] {'task_lines': 'oops', 'summary': 'bad'}"]


def test_emit_renders_swarm_runtime(monkeypatch):
    swarm_calls: list[tuple[list[str], str]] = []

    monkeypatch.setattr(
        "ouro.interfaces.tui.tui_progress.terminal_ui.print_swarm_summary",
        lambda lines, title="Swarm": swarm_calls.append((list(lines), title)),
    )
    monkeypatch.setattr(
        "ouro.interfaces.tui.tui_progress.terminal_ui.print_info",
        lambda msg: None,
    )

    sink = TuiProgressSink()
    sink.emit(
        ProgressEvent(
            kind="swarm_header",
            payload={"line": "Swarm selected: complexity=0.82, subtasks=2", "title": "Swarm"},
        )
    )
    sink.emit(ProgressEvent(kind="swarm_reset", payload={"keep_headers": True}))
    sink.emit(
        ProgressEvent(
            kind="swarm_plan_item",
            payload={"line": "#1 Inspect rendering", "title": "Swarm Plan"},
        )
    )
    sink.emit(
        ProgressEvent(
            kind="swarm_plan_item",
            payload={"line": "#2 Update output", "title": "Swarm Plan"},
        )
    )
    sink.emit(
        ProgressEvent(
            kind="swarm_header",
            payload={"line": "Starting swarm with 2 agent(s)...", "title": "Swarm"},
        )
    )
    sink.emit(ProgressEvent(kind="swarm_agent", payload={"agent": "agent-1", "title": "Swarm"}))
    sink.emit(
        ProgressEvent(
            kind="swarm_assignment",
            payload={
                "agent": "agent-1",
                "assignment": "task #1: Inspect rendering",
                "title": "Swarm",
            },
        )
    )
    sink.emit(
        ProgressEvent(
            kind="swarm_status",
            payload={
                "line": "Swarm complete: 2/2 tasks done, 0 running, 0 blocked",
                "title": "Swarm Result",
            },
        )
    )

    assert swarm_calls[-1] == (
        [
            "Swarm selected: complexity=0.82, subtasks=2",
            "Starting swarm with 2 agent(s)...",
            "",
            "Plan:",
            "#1 Inspect rendering",
            "#2 Update output",
            "",
            "Agents: agent-1",
            "",
            "Assignments:",
            "- agent-1: task #1: Inspect rendering",
            "",
            "Swarm complete: 2/2 tasks done, 0 running, 0 blocked",
        ],
        "Swarm Result",
    )


def test_emit_info_prefixes_subagent_source(monkeypatch):
    infos: list[str] = []

    monkeypatch.setattr(
        "ouro.interfaces.tui.tui_progress.terminal_ui.print_info",
        lambda msg: infos.append(msg),
    )

    sink = TuiProgressSink()
    sink.emit(
        ProgressEvent(
            kind="info",
            payload={"message": "hello world"},
            source=EventSource(agent_id="agent-2", root_agent_id="root", depth=1),
        )
    )

    assert infos == ["[agent-2] hello world"]


def test_emit_tool_call_prefixes_subagent_source(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(
        "ouro.interfaces.tui.tui_progress.terminal_ui.print_tool_call",
        lambda name, arguments: calls.append((name, arguments)),
    )

    sink = TuiProgressSink()
    sink.emit(
        ProgressEvent(
            kind="tool_call",
            payload={"name": "read_file", "arguments": {"file_path": "a.py"}},
            source=EventSource(agent_id="agent-2", root_agent_id="root", depth=1),
        )
    )

    assert calls == [("[agent-2] read_file", {"file_path": "a.py"})]


def test_emit_info_keeps_root_source_unprefixed(monkeypatch):
    infos: list[str] = []

    monkeypatch.setattr(
        "ouro.interfaces.tui.tui_progress.terminal_ui.print_info",
        lambda msg: infos.append(msg),
    )

    sink = TuiProgressSink()
    sink.emit(
        ProgressEvent(
            kind="info",
            payload={"message": "hello world"},
            source=EventSource(agent_id="root", root_agent_id="root", role="root"),
        )
    )

    assert infos == ["hello world"]


def test_emit_info_falls_back_to_plain_info(monkeypatch):
    infos: list[str] = []

    monkeypatch.setattr(
        "ouro.interfaces.tui.tui_progress.terminal_ui.print_info",
        lambda msg: infos.append(msg),
    )

    sink = TuiProgressSink()
    sink.emit(ProgressEvent(kind="info", payload={"message": "hello world"}))

    assert infos == ["hello world"]
