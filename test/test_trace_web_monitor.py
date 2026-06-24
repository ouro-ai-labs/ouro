from __future__ import annotations

import sqlite3
from pathlib import Path

from ouro.core.tracing import SQLiteTraceExporter, TraceEventType, Tracer
from ouro.interfaces.trace_web.server import get_latest_run_id, get_run_events, list_runs


async def _write_sample_trace(db_path: Path) -> None:
    tracer = Tracer(exporter=SQLiteTraceExporter(db_path), run_id="run-web")
    async with tracer.span(TraceEventType.RUN, "agent.run"):
        async with tracer.span(TraceEventType.LLM_CALL, "llm.call") as llm_span:
            llm_span.set_attributes({"llm.model": "test/model", "llm.total_tokens": 7})
        async with tracer.span(TraceEventType.TOOL_CALL, "grep_content") as tool_span:
            tool_span.set_attributes({"tool.result_length": 42})


async def test_list_runs_summarizes_trace_database(tmp_path: Path) -> None:
    db_path = tmp_path / "trace.db"
    await _write_sample_trace(db_path)

    runs = list_runs(db_path)

    assert len(runs) == 1
    run = runs[0]
    assert run.run_id == "run-web"
    assert run.status == "completed"
    assert run.duration_ms is not None
    assert run.llm_calls == 1
    assert run.tool_calls == 1
    assert run.event_count == 6


async def test_get_latest_run_and_events(tmp_path: Path) -> None:
    db_path = tmp_path / "trace.db"
    await _write_sample_trace(db_path)

    assert get_latest_run_id(db_path) == "run-web"
    events = get_run_events(db_path, "run-web")

    assert {event["event_type"] for event in events} == {"run", "llm_call", "tool_call"}
    completed_llm = next(
        event
        for event in events
        if event["event_type"] == "llm_call" and event["status"] == "completed"
    )
    assert completed_llm["attributes"]["llm.total_tokens"] == 7
    assert completed_llm["parent_span_id"] is not None


async def test_events_include_stable_write_sequence(tmp_path: Path) -> None:
    db_path = tmp_path / "trace.db"
    await _write_sample_trace(db_path)

    events = get_run_events(db_path, "run-web")

    assert [event["sequence"] for event in events] == sorted(event["sequence"] for event in events)
    assert events[0]["status"] == "started"


async def test_latest_run_uses_write_order_not_timestamp_only(tmp_path: Path) -> None:
    db_path = tmp_path / "trace.db"
    await _write_sample_trace(db_path)
    tracer = Tracer(exporter=SQLiteTraceExporter(db_path), run_id="run-newer")
    async with tracer.span(TraceEventType.RUN, "agent.run"):
        pass

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE trace_events SET timestamp = '1900-01-01T00:00:00Z' WHERE run_id = 'run-newer'"
        )
        connection.commit()

    assert get_latest_run_id(db_path) == "run-newer"
    assert list_runs(db_path)[0].run_id == "run-newer"


def test_missing_trace_database_returns_empty_results(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"

    assert list_runs(missing) == []
    assert get_latest_run_id(missing) is None
    assert get_run_events(missing, "missing") == []
