from __future__ import annotations

import io
import json

from ouro.core.loop import EventSource, ProgressEvent
from ouro.interfaces.tui.json_progress import JsonProgressSink


def test_json_progress_sink_emits_records_from_progress_events():
    stream = io.StringIO()
    sink = JsonProgressSink(stream=stream)

    sink.emit(ProgressEvent(kind="info", payload={"message": "hello"}))
    sink.emit(ProgressEvent(kind="swarm_status", payload={"line": "Swarm status: 1/2 done"}))
    sink.emit(
        ProgressEvent(
            kind="tool_call",
            payload={"name": "read_file", "arguments": {"file_path": "a.py"}},
        )
    )
    sink.emit(ProgressEvent(kind="tool_result", payload={"text": "ok"}))
    sink.emit(ProgressEvent(kind="final_answer", payload={"text": "done"}))

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines == [
        {"kind": "info", "payload": {"message": "hello"}},
        {"kind": "swarm_status", "payload": {"line": "Swarm status: 1/2 done"}},
        {
            "kind": "tool_call",
            "payload": {"name": "read_file", "arguments": {"file_path": "a.py"}},
        },
        {"kind": "tool_result", "payload": {"text": "ok"}},
        {"kind": "final_answer", "payload": {"text": "done"}},
    ]


def test_json_progress_sink_emits_event_source_metadata():
    stream = io.StringIO()
    sink = JsonProgressSink(stream=stream)

    sink.emit(
        ProgressEvent(
            kind="info",
            payload={"message": "hello"},
            source=EventSource(agent_id="agent-1", root_agent_id="root", depth=1),
        )
    )

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines == [
        {
            "kind": "info",
            "payload": {"message": "hello"},
            "source": {"agent_id": "agent-1", "root_agent_id": "root", "depth": 1},
        }
    ]


def test_json_progress_sink_emits_session_loaded_record():
    stream = io.StringIO()
    sink = JsonProgressSink(stream=stream)

    sink.on_session_loaded([object(), object()])

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines == [{"kind": "session_loaded", "payload": {"count": 2}}]
