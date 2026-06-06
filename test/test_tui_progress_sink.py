from __future__ import annotations

from ouro.interfaces.tui.tui_progress import TuiProgressSink


def test_info_renders_task_list_with_summary(monkeypatch):
    calls: list[tuple[list[str], str | None]] = []
    infos: list[str] = []

    monkeypatch.setattr(
        "ouro.interfaces.tui.tui_progress.terminal_ui.print_task_summary",
        lambda task_lines, summary=None, title="Tasks": calls.append((task_lines, summary)),
    )
    monkeypatch.setattr(
        "ouro.interfaces.tui.tui_progress.terminal_ui.print_info",
        lambda msg: infos.append(msg),
    )

    sink = TuiProgressSink()
    sink.info(
        "Tasks:\n[pending] #1 Task A\n[running] #2 Task B\n\nSummary: 0 done, 1 running, 0 blocked, 1 pending"
    )

    assert calls == [
        (
            ["[pending] #1 Task A", "[running] #2 Task B"],
            "Summary: 0 done, 1 running, 0 blocked, 1 pending",
        )
    ]
    assert infos == []


def test_event_renders_task_list_with_summary(monkeypatch):
    calls: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        "ouro.interfaces.tui.tui_progress.terminal_ui.print_task_summary",
        lambda task_lines, summary=None, title="Tasks": calls.append((task_lines, summary)),
    )

    sink = TuiProgressSink()
    sink.event(
        "task_list",
        {
            "task_lines": ["[pending] #1 Task A", "[running] #2 Task B"],
            "summary": "Summary: 0 done, 1 running, 0 blocked, 1 pending",
        },
    )

    assert calls == [
        (
            ["[pending] #1 Task A", "[running] #2 Task B"],
            "Summary: 0 done, 1 running, 0 blocked, 1 pending",
        )
    ]


def test_event_renders_swarm_runtime(monkeypatch):
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
    sink.event(
        "swarm_header", {"line": "Swarm selected: complexity=0.82, subtasks=2", "title": "Swarm"}
    )
    sink.event("swarm_reset", {"keep_headers": True})
    sink.event("swarm_plan_item", {"line": "#1 Inspect rendering", "title": "Swarm Plan"})
    sink.event("swarm_plan_item", {"line": "#2 Update output", "title": "Swarm Plan"})
    sink.event("swarm_header", {"line": "Starting swarm with 2 agent(s)...", "title": "Swarm"})
    sink.event("swarm_agent", {"agent": "agent-1", "title": "Swarm"})
    sink.event(
        "swarm_assignment",
        {"agent": "agent-1", "assignment": "task #1: Inspect rendering", "title": "Swarm"},
    )
    sink.event(
        "swarm_status",
        {"line": "Swarm complete: 2/2 tasks done, 0 running, 0 blocked", "title": "Swarm Result"},
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


def test_info_falls_back_to_plain_info(monkeypatch):
    infos: list[str] = []

    monkeypatch.setattr(
        "ouro.interfaces.tui.tui_progress.terminal_ui.print_info",
        lambda msg: infos.append(msg),
    )

    sink = TuiProgressSink()
    sink.info("hello world")

    assert infos == ["hello world"]
