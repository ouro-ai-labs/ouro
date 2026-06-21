# RFC: Agent Tracing Monitor

- Status: Draft
- Authors: ouro-ai-lab
- Date: 2026-06-21

## Summary

Add a tracing monitor system for ouro agent execution. The first slice introduces a low-overhead trace event model and exporter pipeline so single-agent runs, tool calls, LLM calls, task execution, and swarm workers can emit structured, realtime-observable spans. Later slices can build CLI/TUI/Web monitors and optional OpenTelemetry-compatible export on top of the same trace stream.

## Problem

ouro can execute increasingly complex work: single-agent ReAct loops, tool calls, memory operations, Task V2 graphs, and swarm-style multi-agent execution. Today, users and developers mostly infer progress from logs, final answers, and ad-hoc progress events.

That is not enough for complex runs. For example, when a swarm run stalls or produces a poor final synthesis, the user needs to answer:

- Which agent or task is currently running?
- Which task blocked which other task?
- Which tool or LLM call failed, timed out, or retried?
- How long did each phase take?
- Which worker produced the artifact used by the synthesizer?
- Did the trace leak sensitive prompt, API key, or filesystem data?

Without a first-class trace model, every monitor UI would need to reconstruct execution state from unrelated logs, which is brittle and incomplete.

## Goals

- Provide a shared trace event/span model for agent execution.
- Preserve parent-child relationships across runs, agents, tasks, tool calls, LLM calls, memory operations, and swarm workers.
- Support realtime event streaming and durable JSONL export in the first implementation slice.
- Make tracing opt-in or explicitly configurable, with minimal overhead when disabled.
- Keep tracing safe by default: redact secrets, avoid storing full prompts/tool outputs unless explicitly configured, and bound payload sizes.
- Support concurrent tasks and agent swarm execution without losing context propagation.
- Keep the initial monitor implementation incremental: emit structured events first, then add richer viewers.
- Preserve the existing three-layer architecture: core tracing primitives in `ouro.core`, capabilities instrumentation in `ouro.capabilities`, and CLI/TUI/Web display in `ouro.interfaces`.

## Non-goals

- Build a full hosted observability backend in the first slice.
- Require tracing for all ouro runs.
- Replace existing logs, progress sinks, or task stores.
- Store full LLM prompts/responses, tool outputs, or memory contents by default.
- Redesign Task V2, swarm scheduling, or the ReAct loop as part of this RFC.
- Implement distributed remote tracing across machines in the first slice.
- Make OpenTelemetry a hard runtime dependency.

## Proposed Behavior (User-Facing)

Tracing can be enabled for a run and observed in realtime or saved for later inspection.

- CLI / UX changes:
  - Add an opt-in trace mode, for example:
    - `python main.py --task "..." --trace`
    - `python main.py --task "..." --trace-file .ouro/traces/<run_id>.jsonl`
  - Add follow-up monitor commands in a later slice, for example:
    - `ouro trace watch <run_id>` to stream active spans/events.
    - `ouro trace view <trace.jsonl>` to inspect a saved trace.
    - `ouro trace serve` to start a local monitor UI.
- Config changes:
  - Add optional tracing configuration only after the core event model lands, for example:
    - `tracing.enabled`
    - `tracing.exporters`
    - `tracing.max_payload_bytes`
    - `tracing.capture_prompts` / `tracing.capture_tool_outputs` defaulting to false.
- Output / logging changes:
  - Normal runs remain unchanged when tracing is disabled.
  - When tracing is enabled, ouro emits structured trace events such as `run.started`, `task.completed`, `tool.failed`, and `llm.completed`.
  - Saved traces are newline-delimited JSON for easy inspection and test assertions.

Example saved event shape:

```json
{
  "event_id": "evt_01...",
  "run_id": "run_01...",
  "span_id": "span_01...",
  "parent_span_id": "span_parent...",
  "timestamp": "2026-06-21T12:00:00.000Z",
  "event_type": "tool_call",
  "name": "grep_content",
  "status": "completed",
  "agent_id": "worker-2",
  "task_id": "task-7",
  "duration_ms": 42,
  "attributes": {
    "tool.name": "grep_content",
    "result.status": "ok"
  }
}
```

## Invariants (Must Not Regress)

- Existing agent runs behave the same when tracing is disabled.
- Existing logs and progress sinks continue to work.
- The core loop remains async-first; tracing must not add blocking I/O on hot paths.
- The layer direction remains `ouro.interfaces -> ouro.capabilities -> ouro.core`; core tracing must not import capabilities or interfaces code.
- Trace export must not record API keys, provider auth headers, or secrets from config.
- Trace failures must not fail the user task unless the user explicitly requests strict tracing.
- Swarm/task state remains owned by Task V2 stores; traces observe execution but do not become the source of truth.

## Design Sketch (Minimal)

Introduce a small tracing subsystem with four concepts:

1. `TraceEvent`
   - Immutable serialized event emitted at span lifecycle boundaries or as a log-style event.
   - Required fields: `event_id`, `run_id`, `span_id`, `parent_span_id`, `timestamp`, `event_type`, `name`, `status`, and bounded `attributes`.
   - Optional fields: `agent_id`, `task_id`, `duration_ms`, `error`, `links`.

2. `Tracer` / `Span`
   - Async-safe API for creating nested spans:

```python
async with tracer.span("tool_call", name="grep_content", attributes={"tool.name": "grep_content"}):
    ...
```

   - Uses `contextvars` so concurrent tasks preserve the active run/span context without passing IDs through every call.
   - Provides no-op implementations when tracing is disabled.

3. `TraceExporter`
   - Interface for receiving events.
   - Initial exporters:
     - no-op exporter for disabled tracing.
     - in-memory exporter for tests.
     - JSONL file exporter for local debugging and later monitor replay.
     - stdout/debug exporter only for development.
   - Exporters should be async-compatible and failure-isolated.

4. Instrumentation points
   - Initial slice should instrument high-value boundaries only:
     - run start/end/failure.
     - agent loop iteration or major phase where available.
     - tool call start/end/failure.
     - LLM call start/end/failure with provider/model/latency/token counts when available.
     - Task V2 task claim/start/end/failure.
     - swarm worker start/end and task assignment.
   - Later slices can add memory read/write events, compaction, verification, planning, synthesis, and richer token/cost summaries.

Suggested package placement:

```text
ouro/core/tracing/
  __init__.py
  context.py
  events.py
  exporters.py
  tracer.py
```

Capabilities and interfaces import those core primitives to instrument their own execution paths. This keeps monitor data production separate from monitor display.

### Realtime Monitoring Path

The first implementation should write JSONL as events arrive. A later CLI monitor can follow that file or subscribe to an in-process stream:

```text
runtime spans -> TraceExporter -> JSONL / event bus -> trace watch/view/serve
```

A web monitor is intentionally a later slice. It can reconstruct a tree/timeline from `run_id`, `span_id`, and `parent_span_id` without changing the event schema.

### Safety and Redaction

Trace attributes are metadata, not arbitrary dumps. Defaults should:

- record tool/LLM names, status, duration, token counts, retry counts, and bounded error summaries.
- avoid full prompts, responses, tool outputs, memory blocks, and file contents.
- redact known secret-looking keys and values.
- truncate long strings and large JSON objects.
- include an explicit marker when data was omitted or redacted.

## Alternatives Considered

- Option A: Use only existing logs and progress events.
  - Rejected because logs are text-oriented, do not consistently preserve parent-child relationships, and are hard to replay into a timeline/tree.
- Option B: Adopt OpenTelemetry directly as the only tracing API.
  - Rejected for the first slice because it would add dependency and configuration complexity. The event model should be simple and local first, with an OpenTelemetry exporter later.
- Option C: Build a web dashboard first.
  - Rejected because monitor UI value depends on stable instrumentation. JSONL plus CLI inspection is a smaller foundation.
- Option D: Store traces inside the Task V2 database.
  - Rejected because traces are append-only observability data, while Task V2 stores are execution state. Coupling them would make cleanup and replay harder.

## Test Plan

- Unit tests:
  - trace event serialization and schema stability.
  - nested span parent/child relationships.
  - exception handling marks spans failed and records bounded error data.
  - disabled/no-op tracer has near-zero behavior impact and does not call exporters.
  - `contextvars` preserve span context across concurrent async tasks.
  - JSONL exporter writes valid newline-delimited JSON and survives exporter errors according to policy.
  - redaction/truncation removes known secret keys and bounds payload sizes.
- Targeted tests to run locally:
  - `./scripts/dev.sh test -q test/core/` after core tracing lands.
  - `./scripts/dev.sh test -q test/swarm/ test/tasks/` after swarm/task instrumentation lands.
  - `TYPECHECK_STRICT=1 ./scripts/dev.sh typecheck`.
  - `./scripts/dev.sh importlint`.
- Smoke run (one real CLI run):
  - `python main.py --task "explain what ouro is" --trace --trace-file /tmp/ouro-trace.jsonl`
  - Verify the JSONL file contains a run span plus LLM/tool/task spans when applicable.

## Rollout / Migration

- Backward compatibility:
  - Tracing is disabled by default or no-op unless explicitly enabled.
  - No migration is required for existing users.
  - Existing progress/log behavior remains unchanged.
- Incremental rollout:
  1. Add core tracing primitives, no-op tracer, in-memory exporter, JSONL exporter, and tests.
  2. Wire opt-in CLI/config plumbing for trace file output.
  3. Instrument run, tool, and LLM boundaries.
  4. Instrument Task V2 and swarm execution boundaries.
  5. Add `trace view/watch` CLI or TUI inspection.
  6. Add optional OpenTelemetry exporter and local web monitor if demand justifies it.
- Rollback:
  - Disable tracing via config/flag to return to current behavior.
  - Remove instrumentation calls independently because they should target no-op-safe APIs.

## Risks & Mitigations

- Risk: tracing adds latency or blocking I/O to hot paths.
  - Mitigation: use no-op tracer by default, async-compatible exporters, buffering where needed, and bounded payloads.
- Risk: trace context is lost across concurrent swarm tasks.
  - Mitigation: use `contextvars`; add concurrency tests with parent-child assertions.
- Risk: traces leak secrets or sensitive prompts.
  - Mitigation: default metadata-only capture, central redaction, size limits, and explicit opt-in for prompt/output capture.
- Risk: instrumentation becomes scattered and hard to maintain.
  - Mitigation: instrument only stable boundaries first and prefer context managers/decorators over manual start/end calls.
- Risk: monitor UI depends on unstable internal event names.
  - Mitigation: document a small event taxonomy and treat serialized JSONL fields as a compatibility surface once accepted.
- Risk: exporter failures hide useful traces or break user tasks.
  - Mitigation: make exporter failure policy explicit; default to best-effort with warnings rather than task failure.

## Open Questions

- Should tracing be disabled by default, enabled by a CLI flag, or enabled for debug/development profiles?
- What event names should be considered stable public schema in the first accepted version?
- Should prompt/tool-output capture ever be allowed, or should ouro only support metadata-level traces?
- How should trace files be retained and cleaned up under `~/.ouro/traces/`?
- Should the first realtime monitor follow JSONL files, subscribe to an in-process event bus, or support both?
- What is the right compatibility layer for OpenTelemetry: direct span mapping, JSONL conversion, or an exporter plugin?
