# RFC 003: AsyncIO-First Migration Plan (Non-Blocking Agent Runtime)

- **Status**: Draft
- **Created**: 2026-01-24
- **Author**: ouro Team

## Abstract

This RFC proposes an incremental migration of ouro to an **asyncio-first** runtime. The goal is to make the agent loop, tool execution, LLM calls, and persistence **non-blocking**, enabling safe concurrency, cancellation, and predictable timeouts — while **preserving existing user-visible behavior**.

## Reader Guide

This RFC is written for:

- **Maintainers/reviewers**: to agree on constraints, sequencing, and acceptance criteria.
- **Contributors/agents**: to avoid introducing new blocking runtime code during the migration.

If you only read one section, read: **Goals**, **Design Overview**, and **Implementation Plan**.

## Motivation

Current execution paths contain multiple blocking operations (HTTP, subprocess, SQLite, retry sleeps, interactive input). As the system grows (more tools, parallelism, longer tasks), blocking calls:

- reduce throughput (cannot overlap I/O),
- make cancellation unreliable,
- increase latency and tail risk (one slow tool stalls the whole agent),
- complicate composition (nested event loops, ad-hoc thread pools).

## Goals

- **Single event loop ownership**: no nested `asyncio.run()` inside library code.
- **Non-blocking agent loop**: the main ReAct loop and plan/execute phases are `async`.
- **Async tool execution**: tools can be awaited; blocking tools are isolated behind explicit boundaries.
- **Async LLM calls + retry**: retries do not block and respect cancellation/timeouts.
- **Preserve behavior**: CLI UX, prompts, memory semantics, and tool schemas behave the same unless explicitly changed.
- **Migration-friendly**: enable multiple small PRs with clear acceptance criteria.
- **Minimal API surface bloat**: avoid maintaining parallel sync/async implementations for the same runtime path.

## Non-goals

- Rewriting every tool to “pure async” in the first PR.
- Introducing a second concurrency framework (e.g., Trio/AnyIO) as a dependency.
- Changing the user-facing CLI flags or output format as part of the migration.
- Perfect cancellation of all legacy blocking operations (see Risks for `to_thread` limitations).

## Terminology

- **Blocking**: a call that blocks the event loop thread (e.g., `requests`, `sqlite3`, `subprocess.run`, `time.sleep`).
- **Async boundary**: a controlled place where blocking work is offloaded (e.g., `asyncio.to_thread`), with timeouts/cancellation handled.
- **Loop owner**: the only code allowed to start/stop the event loop (entrypoints only).

## Scope (Impacted Areas)

This RFC targets the runtime path that executes agent loops and tools:

- **Entrypoints**: `main.py`, `cli.py`, `interactive.py`
- **Agent runtime**: `agent/base.py`, `agent/agent.py`, `agent/plan_execute_agent.py`, `agent/tool_executor.py`
- **LLM layer**: `llm/litellm_adapter.py`, `llm/retry.py`
- **Memory/persistence**: `memory/manager.py`, `memory/store.py`
- **Tools**: `tools/*` (prioritized conversions, not all at once)

## Design Inspirations (Codex / Claude Agent SDK)

This RFC intentionally aligns with patterns proven in production agent runtimes:

**Codex SDK (Thread + events model)**
- A conversation is represented as a **thread** object (`Thread`) whose ID becomes available when a run starts (via an early `thread.started` event). This enables **resume by ID**.
- There are two ergonomic surfaces:
  - `run(...)` → run-to-completion result (final response + items + usage).
  - `runStreamed(...)` → an `AsyncGenerator` of structured **thread events** (e.g., `turn.started`, `item.started/updated/completed`, `turn.completed`, `turn.failed`).
- Streaming is designed around **structured events**, not log parsing. Cleanup is handled with `try/finally` around the streaming loop.
- Cancellation propagates via a **signal** parameter in run options; the implementation is expected to stop streaming and still execute cleanup.

**Claude Agent SDK demos (Session + stream model)**
- A session API tends to separate **send** from **stream**: `await session.send(...)` followed by `for await (msg of session.stream())`.
- Sessions are often treated as long-lived resources and closed via language-native lifecycle primitives (TypeScript `using`; Python analogue: `async with`).

**Shared design theme**
- Keep orchestration and tool side effects behind clear boundaries, and prefer deterministic, structured progress reporting over free-form prints.

Implication for ouro:
- Keep orchestration async-first and structured.
- Prefer producing deterministic, structured progress (even if initially only used internally by the CLI/TUI).
- Prefer explicit lifecycle management for long-lived resources (LLM sessions, DB connections, subprocess handles).

## Phases at a Glance

| Phase | Status | Primary change | Key acceptance |
|------:|--------|----------------|----------------|
| 0 | Done | RFC + repo rules | Docs point to RFC |
| 1 | Done | Single loop ownership | No `asyncio.run()` in library code |
| 2 | Done | Async agent loop + async tool executor boundary | ReAct works end-to-end; tool order unchanged |
| 3 | Done | Async LLM + async retry backoff | Retries don’t block; cancellation stops backoff |
| 4 | Done | Convert high-impact blocking tools | HTTP/subprocess/DB no longer depend on `to_thread` |
| 5 | Deferred (Optional) | Constrained tool parallelism | Faster when safe; still deterministic outputs |

## Design Overview

### 1) Event loop ownership

Rule: `asyncio.run()` is only allowed in top-level entrypoints (e.g., `main.py` / `cli.py`).

Library code (agents/tools/memory/llm) must assume an event loop may already be running and must never call `asyncio.run()`.

### 2) Async agent runtime (in-place, minimal duplication)

To avoid “two APIs” and wrapper bloat, we prefer **in-place signature upgrades**:

- `BaseAgent._react_loop(...)` becomes `async def _react_loop(...)`.
- `ReActAgent.run(...)` and `PlanExecuteAgent.run(...)` become `async def run(...)`.
- `main.py` becomes the loop owner and awaits agent execution.

This is a large mechanical change but keeps code paths singular (no parallel sync/async implementations).

### 3) Tools: async execution with controlled blocking fallbacks

Tool execution becomes awaitable at the executor layer.

Migration invariant (Phase 2–4 compatibility):
- Tool interfaces converge on a single **async** entrypoint: `async def execute(...) -> str`.
- The tool executor assumes async execution (no sync fallbacks / `to_thread` in runtime paths).
- New/modified tools should prefer native async libraries for I/O-heavy work (HTTP, subprocess, DB) so timeouts and cancellation can be enforced reliably.

Notes:
- `asyncio.to_thread(...)` isolates blocking work but does **not** forcibly stop the underlying work on cancellation; it only cancels the await. For side-effecting operations, native async implementations (or explicit process cancellation) are preferred.

### 3.1) LLM calls: async-only interface

The LLM adapter exposes a single async entrypoint.

- The agent runtime calls `await llm.call_async(...)` (no sync fallbacks).
- If the underlying provider library is synchronous, the async boundary belongs in the adapter (not in agent code).

### 4) Concurrency semantics (safe by default)

To preserve existing behavior, the default for tool calls within a single LLM turn is:

- **Serial execution** (deterministic order, minimal risk).

Optional later enhancement (separate PR):
- **Constrained parallelism** for read-only/non-conflicting tools, with explicit limits (semaphores) and tool-level concurrency metadata.

### 4.1) Optional: Structured progress events (CLI/TUI-friendly)

As the runtime becomes async-first, we may introduce an internal “event stream” interface for observability
and interactive UX (inspired by streamed APIs in other agent runtimes).

Non-goal for early phases: changing user-visible output. The initial implementation can keep current printing,
but it should be easy to evolve the runtime to emit structured events such as:

- `turn.started`, `turn.completed`
- `llm.requested`, `llm.responded`
- `tool.called`, `tool.succeeded`, `tool.failed`

This makes testing and UI integration simpler than parsing logs.

### 5) Cancellation + timeouts

All awaited operations should be cancellable. Timeouts should be applied consistently at boundaries:

- LLM call timeout (already configured) must not block.
- Tool execution must respect timeouts, especially subprocess and HTTP.
- Retry backoff must use `await asyncio.sleep(...)` and allow cancellation.

Recommended primitives (Python 3.12+):
- Use `asyncio.timeout(...)` (or `asyncio.wait_for`) for boundary timeouts.
- Use `asyncio.TaskGroup` for structured concurrency (instead of ad-hoc task lists).
- In async code, prefer `asyncio.get_running_loop()` over `get_event_loop()`.

## Implementation Plan (phased PRs)

### Phase 0 — Documentation + rules (PR 1)

- Add this RFC.
- Update contributor guidance (AGENTS/docs) to enforce async-first patterns for new code during the migration.

**Acceptance**
- RFC merged and referenced by AGENTS/docs.

### Phase 1 — Event loop ownership (PR 2)

- Remove nested `asyncio.run()` usage from library code (notably plan/execute internals).
- Make `main.py`/interactive entrypoints the single loop owner.

**Acceptance**
- No `asyncio.run()` outside entrypoints.
- CLI still works; plan/execute exploration and step batching still run.

**Status**
- Completed.

### Phase 2 — Async core loop + tool executor (PR 3–4)

- Convert `BaseAgent._react_loop` to async.
- Convert `ToolExecutor.execute_tool_call` to async and use `asyncio.to_thread(...)` for existing tools.
- Keep tool schemas unchanged.

**Acceptance**
- ReAct agent completes tasks end-to-end under `asyncio.run()` from the entrypoint.
- Tool calls behave the same (order, outputs).

**Status**
- Completed.

### Phase 3 — Async LLM + retry backoff (PR 5)

- Add async LLM call path (depending on LiteLLM support) and update the agent to await it.
- Make retry logic async (`await asyncio.sleep`).

**Acceptance**
- Retries no longer block the loop; cancellation interrupts backoff.

**Status**
- Completed.

### Phase 4 — Convert high-impact blocking tools (PR 6+)

Prioritize by impact:
- HTTP fetch (`requests` → async client)
- shell/git subprocess execution (`subprocess.run` → asyncio subprocess)
- SQLite persistence (`sqlite3` → async strategy)

**Acceptance**
- These tools no longer require `to_thread` and respect timeouts/cancellation.

**Status**
- Completed.

### Post-Phase-4 Follow-ups (Recommended)

These are reliability/consistency improvements now that async migration is complete:

- **Unify tool timeouts** at the executor layer (with per-tool overrides) to simplify tool code and ensure consistent cancellation behavior.
- **Serialize memory persistence writes** (e.g., `asyncio.Lock` or a single writer task) to avoid concurrent write hazards when steps run in parallel. (Implemented: `MemoryStore` write lock)

### Phase 5 — Optional constrained parallel tool calls (Deferred)

- Introduce tool concurrency metadata (read-only / writes-paths / external side effects).
- Allow parallel execution when safe, with a global concurrency cap.

**Acceptance**
- Measurable latency/throughput improvements on safe workloads.
- No regressions on deterministic order of returned tool messages.

## Testing & Verification

Each phase PR should include at least:

- **Static checks**:
  - Confirm `asyncio.run(` only appears in entrypoints.
  - Confirm no new blocking calls were introduced in runtime paths (`time.sleep`, `requests`, `sqlite3`, `subprocess.run`).
- **Behavior checks**:
  - Run a basic smoke task end-to-end via CLI.
  - Run the unit test suite relevant to the changed area (agent loop, tools, memory, etc.).

## Coding Rules During Migration

These rules apply to all new code and refactors while the migration is in progress:

1. **No `asyncio.run()` in library code** (agents/tools/memory/llm).
2. **No blocking sleeps**: use `await asyncio.sleep(...)` in async code.
3. **Blocking I/O must be behind an async boundary** (executor or native async).
4. **Prefer deterministic behavior**: keep tool call order stable unless a feature explicitly changes it.
5. **Document new async APIs** in `docs/extending.md` when they land.
6. Prefer structured concurrency (`asyncio.TaskGroup`) for parallel work.
7. Avoid `asyncio.get_event_loop()` in new async code; use `get_running_loop()`.
8. Keep async boundaries centralized (prefer the executor/runtime layer over sprinkling `to_thread` across tools).
9. Do not swallow cancellation: avoid blanket `except Exception` in async runtime paths; re-raise `asyncio.CancelledError`.

## Suggested Enforcement (Optional)

To reduce migration drift, consider lightweight repo checks (CI or pre-commit):

- Reject `asyncio.run(` outside entrypoints.
- Flag common blocking calls in runtime paths (`time.sleep`, `requests`, `sqlite3`, `subprocess.run`).

## Risks & Mitigations

- **Large mechanical diff**: mitigate with phased PRs and strict acceptance checks.
- **Hidden blocking calls**: mitigate with code review rules + grep checks (`requests`, `sqlite3`, `subprocess.run`, `time.sleep`) in agent runtime paths.
- **Cancellation complexity**: mitigate by adding timeouts at boundaries and ensuring subprocess cleanup.
- **`to_thread` cancellation semantics**: mitigate by keeping serial semantics by default and prioritizing native async rewrites for side-effecting tools (HTTP/subprocess/DB).

## Open Questions

- What is the minimal tool concurrency metadata that provides value without heavy annotation burden?
- Do we want to standardize timeouts at the executor layer or per-tool?
- Should memory persistence be serialized via a single async “writer task” (actor) to avoid concurrent write hazards?
