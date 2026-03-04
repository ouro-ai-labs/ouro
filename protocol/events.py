"""JSONL protocol event schema and validation helpers.

This module defines v1 event contracts for `--mode jsonl` and provides
schema/stream validators that can be used by emitters and tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

SCHEMA_VERSION = "1.0"

EVENT_RUN_START = "run_start"
EVENT_STEP_START = "step_start"
EVENT_TOOL_CALL = "tool_call"
EVENT_TOOL_RESULT = "tool_result"
EVENT_ASSISTANT_MESSAGE = "assistant_message"
EVENT_ERROR = "error"
EVENT_RUN_END = "run_end"
EVENT_INPUT_EVENT = "input_event"

EVENT_TYPES = {
    EVENT_RUN_START,
    EVENT_STEP_START,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_ERROR,
    EVENT_RUN_END,
}

ERROR_CODES = {
    "llm_error",
    "tool_error",
    "timeout",
    "validation_error",
    "internal_error",
    "budget_exceeded",
    "max_iterations",
}

RUN_END_STATUS = {"success", "failed", "cancelled"}
RUN_MODES = {"cli", "bot", "interactive"}


class ProtocolValidationError(ValueError):
    """Raised when an event payload fails protocol validation."""


def _err(msg: str) -> ProtocolValidationError:
    return ProtocolValidationError(msg)


def _require_type(payload: dict[str, Any], key: str, typ: type) -> Any:
    if key not in payload:
        raise _err(f"missing required field: {key}")
    value = payload[key]
    if not isinstance(value, typ):
        raise _err(f"field '{key}' must be {typ.__name__}, got {type(value).__name__}")
    return value


def _require_non_negative_int(payload: dict[str, Any], key: str) -> int:
    value = _require_type(payload, key, int)
    if value < 0:
        raise _err(f"field '{key}' must be >= 0")
    return value


def _require_positive_int(payload: dict[str, Any], key: str) -> int:
    value = _require_non_negative_int(payload, key)
    if value < 1:
        raise _err(f"field '{key}' must be >= 1")
    return value


def _require_iso8601_utc(ts: str) -> None:
    if not ts.endswith("Z"):
        raise _err("field 'ts' must be ISO8601 UTC and end with 'Z'")
    try:
        datetime.fromisoformat(ts[:-1] + "+00:00")
    except ValueError as exc:
        raise _err(f"field 'ts' is not valid ISO8601 UTC: {ts!r}") from exc


def _validate_run_start(payload: dict[str, Any]) -> None:
    _require_type(payload, "task", str)
    _require_type(payload, "model", str)

    profile = payload.get("profile")
    if profile is not None and not isinstance(profile, str):
        raise _err("field 'profile' must be string or null")

    tools = _require_type(payload, "tools", list)
    if not all(isinstance(name, str) for name in tools):
        raise _err("field 'tools' must be list[str]")

    _require_type(payload, "cwd", str)
    _require_type(payload, "version", str)

    mode = payload.get("mode")
    if mode is not None:
        if not isinstance(mode, str):
            raise _err("field 'mode' must be string when present")
        if mode not in RUN_MODES:
            raise _err(f"field 'mode' must be one of {sorted(RUN_MODES)}")


def _validate_step_start(payload: dict[str, Any]) -> None:
    _require_positive_int(payload, "step")


def _validate_tool_call(payload: dict[str, Any]) -> None:
    _require_positive_int(payload, "step")
    _require_type(payload, "call_id", str)
    _require_type(payload, "tool_name", str)
    _require_type(payload, "args", dict)
    _require_type(payload, "readonly", bool)


def _validate_tool_result(payload: dict[str, Any]) -> None:
    _require_positive_int(payload, "step")
    _require_type(payload, "call_id", str)
    _require_type(payload, "ok", bool)
    _require_non_negative_int(payload, "duration_ms")

    preview = payload.get("output_preview")
    if preview is not None and not isinstance(preview, str):
        raise _err("field 'output_preview' must be string when present")

    out_ref = payload.get("output_ref")
    if out_ref is not None and not isinstance(out_ref, str):
        raise _err("field 'output_ref' must be string when present")

    err_code = payload.get("error_code")
    if err_code is not None and not isinstance(err_code, str):
        raise _err("field 'error_code' must be string when present")


def _validate_assistant_message(payload: dict[str, Any]) -> None:
    _require_positive_int(payload, "step")
    _require_type(payload, "content", str)


def _validate_error(payload: dict[str, Any]) -> None:
    step = payload.get("step")
    if step is not None and (not isinstance(step, int) or step < 1):
        raise _err("field 'step' must be >= 1 int or null")

    code = _require_type(payload, "code", str)
    if code not in ERROR_CODES:
        raise _err(f"field 'code' must be one of {sorted(ERROR_CODES)}")

    _require_type(payload, "message", str)
    _require_type(payload, "retriable", bool)


def _validate_run_end(payload: dict[str, Any]) -> None:
    status = _require_type(payload, "status", str)
    if status not in RUN_END_STATUS:
        raise _err(f"field 'status' must be one of {sorted(RUN_END_STATUS)}")

    usage = _require_type(payload, "usage", dict)
    _require_non_negative_int(usage, "input_tokens")
    _require_non_negative_int(usage, "output_tokens")
    _require_non_negative_int(usage, "total_steps")

    cost = usage.get("cost_usd")
    if not isinstance(cost, (int, float)):
        raise _err("field 'usage.cost_usd' must be number")
    if cost < 0:
        raise _err("field 'usage.cost_usd' must be >= 0")

    _require_non_negative_int(payload, "duration_ms")

    final_answer = payload.get("final_answer")
    if final_answer is not None and not isinstance(final_answer, str):
        raise _err("field 'final_answer' must be string when present")


def _validate_input_event_fields(payload: dict[str, Any]) -> None:
    input_id = _require_type(payload, "input_id", str)
    if not input_id:
        raise _err("field 'input_id' must be non-empty string")

    input_type = _require_type(payload, "input_type", str)
    if not input_type:
        raise _err("field 'input_type' must be non-empty string")

    _require_type(payload, "payload", dict)

    source = payload.get("source")
    if source is not None and not isinstance(source, str):
        raise _err("field 'source' must be string when present")

    target_step = payload.get("target_step")
    if target_step is not None and (not isinstance(target_step, int) or target_step < 1):
        raise _err("field 'target_step' must be >= 1 int when present")


def _validate_common_envelope(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise _err("event must be an object")

    version = _require_type(payload, "schema_version", str)
    if version != SCHEMA_VERSION:
        raise _err(f"unsupported schema_version: {version!r}, expected {SCHEMA_VERSION!r}")

    _require_type(payload, "run_id", str)

    event = _require_type(payload, "event", str)

    ts = _require_type(payload, "ts", str)
    _require_iso8601_utc(ts)
    return event


def validate_event(payload: dict[str, Any]) -> None:
    """Validate a single JSONL protocol event payload.

    Raises:
        ProtocolValidationError: if payload violates schema.
    """
    event = _validate_common_envelope(payload)
    if event not in EVENT_TYPES:
        raise _err(f"field 'event' must be one of {sorted(EVENT_TYPES)}")

    if event == EVENT_RUN_START:
        _validate_run_start(payload)
    elif event == EVENT_STEP_START:
        _validate_step_start(payload)
    elif event == EVENT_TOOL_CALL:
        _validate_tool_call(payload)
    elif event == EVENT_TOOL_RESULT:
        _validate_tool_result(payload)
    elif event == EVENT_ASSISTANT_MESSAGE:
        _validate_assistant_message(payload)
    elif event == EVENT_ERROR:
        _validate_error(payload)
    elif event == EVENT_RUN_END:
        _validate_run_end(payload)


def validate_input_event(payload: dict[str, Any]) -> None:
    """Validate a reserved inbound ``input_event`` payload.

    This schema is intentionally reserved for future bidirectional protocol work.
    Current runtime behavior does not execute injected events.
    """
    event = _validate_common_envelope(payload)
    if event != EVENT_INPUT_EVENT:
        raise _err(f"field 'event' must be {EVENT_INPUT_EVENT!r}")

    _validate_input_event_fields(payload)


def validate_event_stream(events: list[dict[str, Any]]) -> None:
    """Validate cross-event invariants for one run.

    Raises:
        ProtocolValidationError: if stream-level invariants are violated.
    """
    if not events:
        raise _err("event stream must not be empty")

    run_id: str | None = None
    run_end_seen = 0
    seen_tool_calls: set[str] = set()

    for i, event in enumerate(events):
        validate_event(event)
        if i == 0 and event["event"] != EVENT_RUN_START:
            raise _err("event stream must start with run_start")

        current_run_id = event["run_id"]
        if run_id is None:
            run_id = current_run_id
        elif current_run_id != run_id:
            raise _err("all events in a stream must share the same run_id")

        name = event["event"]
        if name == EVENT_TOOL_CALL:
            call_id = event["call_id"]
            if call_id in seen_tool_calls:
                raise _err(f"duplicate tool_call call_id: {call_id}")
            seen_tool_calls.add(call_id)
        elif name == EVENT_TOOL_RESULT:
            call_id = event["call_id"]
            if call_id not in seen_tool_calls:
                raise _err(f"tool_result references unknown call_id: {call_id}")
        elif name == EVENT_RUN_END:
            run_end_seen += 1
            if i != len(events) - 1:
                raise _err("run_end must be the final event in the stream")

    if run_end_seen != 1:
        raise _err("event stream must contain exactly one run_end event")
