"""Contract tests for JSONL protocol event schema validation."""

from __future__ import annotations

import pytest

from protocol.events import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_RUN_END,
    EVENT_RUN_START,
    EVENT_STEP_START,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    ProtocolValidationError,
    SCHEMA_VERSION,
    validate_event,
    validate_event_stream,
)


def _base(event: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": "run-123",
        "event": event,
        "ts": "2026-03-04T23:00:00Z",
    }


def test_validate_run_start_event() -> None:
    payload = _base(EVENT_RUN_START)
    payload.update(
        {
            "task": "list files",
            "model": "openai/gpt-4o",
            "profile": "reviewer",
            "tools": ["read_file", "grep_content"],
            "cwd": "/tmp/project",
            "version": "0.4.0",
        }
    )
    validate_event(payload)


def test_invalid_common_field_rejected() -> None:
    payload = _base(EVENT_STEP_START)
    payload["schema_version"] = "2.0"
    payload["step"] = 1

    with pytest.raises(ProtocolValidationError, match="unsupported schema_version"):
        validate_event(payload)


def test_tool_call_requires_readonly() -> None:
    payload = _base(EVENT_TOOL_CALL)
    payload.update(
        {
            "step": 1,
            "call_id": "c1",
            "tool_name": "grep_content",
            "args": {"pattern": "TODO"},
            "readonly": True,
        }
    )
    validate_event(payload)


def test_error_code_enum_includes_budget_and_max_iterations() -> None:
    payload = _base("error")
    payload.update(
        {
            "step": 2,
            "code": "budget_exceeded",
            "message": "budget reached",
            "retriable": False,
        }
    )
    validate_event(payload)

    payload["code"] = "max_iterations"
    validate_event(payload)


def test_validate_run_end_event_usage_shape() -> None:
    payload = _base(EVENT_RUN_END)
    payload.update(
        {
            "status": "success",
            "usage": {
                "input_tokens": 12,
                "output_tokens": 8,
                "cost_usd": 0.02,
                "total_steps": 3,
            },
            "duration_ms": 1500,
            "final_answer": "done",
        }
    )
    validate_event(payload)


def test_stream_invariant_requires_single_final_run_end() -> None:
    events = []

    start = _base(EVENT_RUN_START)
    start.update(
        {
            "task": "x",
            "model": "m",
            "profile": None,
            "tools": [],
            "cwd": "/tmp",
            "version": "0.1.0",
        }
    )
    events.append(start)

    step = _base(EVENT_STEP_START)
    step.update({"step": 1, "ts": "2026-03-04T23:00:01Z"})
    events.append(step)

    call = _base(EVENT_TOOL_CALL)
    call.update(
        {
            "step": 1,
            "call_id": "c1",
            "tool_name": "read_file",
            "args": {"path": "a.txt"},
            "readonly": True,
            "ts": "2026-03-04T23:00:02Z",
        }
    )
    events.append(call)

    result = _base(EVENT_TOOL_RESULT)
    result.update(
        {
            "step": 1,
            "call_id": "c1",
            "ok": True,
            "duration_ms": 20,
            "output_preview": "ok",
            "ts": "2026-03-04T23:00:03Z",
        }
    )
    events.append(result)

    msg = _base(EVENT_ASSISTANT_MESSAGE)
    msg.update(
        {
            "step": 1,
            "content": "hello",
            "ts": "2026-03-04T23:00:04Z",
        }
    )
    events.append(msg)

    end = _base(EVENT_RUN_END)
    end.update(
        {
            "status": "success",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 10,
                "cost_usd": 0.1,
                "total_steps": 1,
            },
            "duration_ms": 400,
            "ts": "2026-03-04T23:00:05Z",
        }
    )
    events.append(end)

    validate_event_stream(events)

    bad_events = list(events)
    bad_events.append(end.copy())
    bad_events[-1]["ts"] = "2026-03-04T23:00:06Z"
    with pytest.raises(ProtocolValidationError, match="final event"):
        validate_event_stream(bad_events)

    missing_end = list(events[:-1])
    with pytest.raises(ProtocolValidationError, match="exactly one run_end"):
        validate_event_stream(missing_end)


def test_stream_invariant_rejects_unknown_tool_result_reference() -> None:
    start = _base(EVENT_RUN_START)
    start.update(
        {
            "task": "x",
            "model": "m",
            "profile": None,
            "tools": [],
            "cwd": "/tmp",
            "version": "0.1.0",
        }
    )

    result = _base(EVENT_TOOL_RESULT)
    result.update(
        {
            "step": 1,
            "call_id": "never-called",
            "ok": True,
            "duration_ms": 10,
            "ts": "2026-03-04T23:00:01Z",
        }
    )

    end = _base(EVENT_RUN_END)
    end.update(
        {
            "status": "failed",
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0,
                "total_steps": 1,
            },
            "duration_ms": 20,
            "ts": "2026-03-04T23:00:02Z",
        }
    )

    with pytest.raises(ProtocolValidationError, match="unknown call_id"):
        validate_event_stream([start, result, end])
