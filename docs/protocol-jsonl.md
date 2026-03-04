# JSONL Protocol (v1)

This document defines the machine-readable event contract used by Ouro protocol work.

## Status

- Output event schema validators are implemented in `protocol/events.py`.
- Runtime event emission in CLI loop is being delivered in follow-up slices.
- Inbound `input_event` is reserved for future orchestrator integration and is not executed yet.

## Common Envelope (all events)

All protocol objects share:

- `schema_version` (string, must be `"1.0"`)
- `run_id` (string)
- `event` (string)
- `ts` (ISO8601 UTC string ending with `Z`)

## Output Events (current stream contract)

- `run_start`
- `step_start`
- `tool_call`
- `tool_result`
- `assistant_message`
- `error`
- `run_end`

These are validated by `validate_event()` / `validate_event_stream()`.

## Reserved Input Channel: `input_event`

`input_event` is the reserved inbound message shape for future bidirectional mode. It is validated by `validate_input_event()` and currently treated as a capability reservation only.

### Fields

- `input_id` (string, non-empty)
- `input_type` (string, non-empty, namespaced action name such as `message.append`)
- `payload` (object)
- `source` (optional string; producer identity)
- `target_step` (optional int, `>= 1`; routing hint)

### Validation Rules

1. The common envelope must be valid (`schema_version`, `run_id`, `event`, `ts`).
2. `event` must equal `"input_event"`.
3. `input_id` and `input_type` must be non-empty strings.
4. `payload` must be a JSON object.
5. If present, `source` must be a string.
6. If present, `target_step` must be an integer >= 1.

## Capability Boundary

- Implemented now:
  - Schema validators for output events.
  - Schema validator for reserved inbound `input_event`.
  - CLI reservation flag `--input-events PATH` (no-op).
- Not implemented yet:
  - Live ingestion/execution of inbound `input_event`.
  - Duplex transport over stdin/stdout or network RPC.
