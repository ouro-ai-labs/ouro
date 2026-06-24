from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from ouro.core.tracing import (
    InMemoryTraceExporter,
    JSONLTraceExporter,
    SQLiteTraceExporter,
    TraceEventType,
    Tracer,
    get_current_span_id,
    resolve_sqlite_trace_db_path,
    sanitize_attributes,
)


async def test_nested_spans_preserve_parent_child_relationships() -> None:
    exporter = InMemoryTraceExporter()
    tracer = Tracer(exporter=exporter, run_id="run-test")

    async with tracer.span(TraceEventType.RUN, "run") as parent:
        assert get_current_span_id() == parent.span_id
        async with tracer.span(TraceEventType.TOOL_CALL, "tool") as child:
            assert get_current_span_id() == child.span_id

    assert [event.status for event in exporter.events] == [
        "started",
        "started",
        "completed",
        "completed",
    ]
    parent_started, child_started, child_completed, parent_completed = exporter.events
    assert parent_started.run_id == "run-test"
    assert parent_started.parent_span_id is None
    assert child_started.parent_span_id == parent.span_id
    assert child_completed.parent_span_id == parent.span_id
    assert parent_completed.duration_ms is not None


async def test_failed_span_records_bounded_error_and_reraises() -> None:
    exporter = InMemoryTraceExporter()
    tracer = Tracer(exporter=exporter)

    with pytest.raises(ValueError, match="bad input"):
        async with tracer.span(TraceEventType.LLM_CALL, "llm"):
            raise ValueError("bad input")

    failed = exporter.events[-1]
    assert failed.status == "failed"
    assert failed.error is not None
    assert failed.error.type == "ValueError"
    assert failed.error.message == "bad input"
    assert failed.duration_ms is not None
    assert "ValueError: bad input" in failed.attributes["error.traceback"]


async def test_disabled_tracer_does_not_export_events() -> None:
    exporter = InMemoryTraceExporter()
    tracer = Tracer(exporter=exporter, enabled=False)

    async with tracer.span(TraceEventType.RUN, "run"):
        await tracer.emit_event(TraceEventType.LOG, "ignored")

    assert exporter.events == []


async def test_contextvars_isolate_concurrent_child_spans() -> None:
    exporter = InMemoryTraceExporter()
    tracer = Tracer(exporter=exporter, run_id="run-concurrent")

    async def child(name: str) -> None:
        async with tracer.span(TraceEventType.TASK, name):
            await asyncio.sleep(0)

    async with tracer.span(TraceEventType.RUN, "run") as parent:
        await asyncio.gather(child("a"), child("b"))

    task_started = [
        event
        for event in exporter.events
        if event.event_type == TraceEventType.TASK and event.status == "started"
    ]
    assert len(task_started) == 2
    assert {event.parent_span_id for event in task_started} == {parent.span_id}
    assert {event.run_id for event in task_started} == {"run-concurrent"}


async def test_jsonl_exporter_writes_newline_delimited_json(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    tracer = Tracer(exporter=JSONLTraceExporter(trace_path), run_id="run-jsonl")

    async with tracer.span(TraceEventType.TOOL_CALL, "grep", attributes={"tool.name": "grep"}):
        pass

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    assert payloads[0]["status"] == "started"
    assert payloads[1]["status"] == "completed"
    assert payloads[0]["run_id"] == "run-jsonl"
    assert payloads[0]["attributes"] == {"tool.name": "grep"}


def test_resolve_sqlite_trace_db_path_prefers_configured_path(tmp_path: Path) -> None:
    configured = tmp_path / "configured.db"

    assert resolve_sqlite_trace_db_path(db_path=configured) == configured


def test_resolve_sqlite_trace_db_path_supports_sqlite_urls(tmp_path: Path) -> None:
    configured = tmp_path / "from-url.db"

    assert resolve_sqlite_trace_db_path(database_url="sqlite://" + str(configured)) == configured


def test_resolve_sqlite_trace_db_path_rejects_remote_urls() -> None:
    with pytest.raises(ValueError, match="Unsupported SQLite trace database URL scheme"):
        resolve_sqlite_trace_db_path(database_url="mysql://localhost/ouro_trace")


async def test_sqlite_exporter_writes_queryable_trace_events(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.db"
    tracer = Tracer(exporter=SQLiteTraceExporter(trace_path), run_id="run-sqlite")

    async with tracer.span(
        TraceEventType.TOOL_CALL,
        "grep",
        attributes={"tool.name": "grep", "api_key": "secret"},
        agent_id="agent-1",
        task_id="task-1",
    ):
        pass

    with sqlite3.connect(trace_path) as connection:
        rows = connection.execute(
            """
            SELECT run_id, event_type, name, status, agent_id, task_id,
                   attributes_json, duration_ms
            FROM trace_events
            ORDER BY rowid
            """
        ).fetchall()

    assert len(rows) == 2
    started, completed = rows
    assert started[:6] == (
        "run-sqlite",
        TraceEventType.TOOL_CALL,
        "grep",
        "started",
        "agent-1",
        "task-1",
    )
    assert json.loads(started[6]) == {"api_key": "[redacted]", "tool.name": "grep"}
    assert completed[3] == "completed"
    assert completed[7] is not None


def test_sanitize_attributes_redacts_and_truncates() -> None:
    sanitized = sanitize_attributes(
        {
            "api_key": "secret-value",
            "nested": {"Authorization": "Bearer abc", "safe": "ok"},
            "long": "x" * 8,
        },
        max_string_length=4,
    )

    assert sanitized["api_key"] == "[redacted]"
    assert sanitized["nested"]["Authorization"] == "[redacted]"
    assert sanitized["nested"]["safe"] == "ok"
    assert sanitized["long"] == "xxxx…[truncated]"
    assert (
        sanitize_attributes({"image_url": {"url": "data:image/png;base64,abc"}})["image_url"]
        == "[omitted binary/blob]"
    )


async def test_exporter_failures_do_not_fail_user_work() -> None:
    class FailingExporter:
        async def export(self, event):  # type: ignore[no-untyped-def]
            raise RuntimeError("export failed")

    tracer = Tracer(exporter=FailingExporter())

    async with tracer.span(TraceEventType.RUN, "run"):
        pass
