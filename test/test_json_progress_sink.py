from __future__ import annotations

import io
import json

from ouro.interfaces.tui.json_progress import JsonProgressSink


def test_json_progress_sink_emits_info_and_event_records():
    stream = io.StringIO()
    sink = JsonProgressSink(stream=stream)

    sink.info("hello")
    sink.event("swarm_status", {"line": "Swarm status: 1/2 done"})

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines == [
        {"type": "info", "message": "hello"},
        {"type": "event", "kind": "swarm_status", "payload": {"line": "Swarm status: 1/2 done"}},
    ]


def test_json_progress_sink_emits_tool_and_answer_records():
    stream = io.StringIO()
    sink = JsonProgressSink(stream=stream)

    sink.tool_call("read_file", {"file_path": "a.py"})
    sink.tool_result("ok")
    sink.final_answer("done")

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines[0] == {
        "type": "tool_call",
        "name": "read_file",
        "arguments": {"file_path": "a.py"},
    }
    assert lines[1] == {"type": "tool_result", "result": "ok"}
    assert lines[2] == {"type": "final_answer", "text": "done"}
