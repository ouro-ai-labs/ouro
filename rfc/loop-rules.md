# RFC: Loop Rules (Deterministic Pre-Dispatch Guards)

- Status: Draft
- Authors: Yixin Luo
- Date: 2026-05-23

## Summary

Generalize the hard-coded repeated-tool-call guard in the core agent loop into
a pluggable **Rule** abstraction: deterministic, per-tool-call checks the loop
runs around each call. A rule can **block** a call before it runs (its text
becomes the call's `tool_result`, and the call is skipped) or **rewrite** a
dispatched call's result afterward. A rule never stops the loop; it only blocks
or rewrites individual results. Rules trade a probabilistic LLM mistake for a
deterministic guarantee.

## Problem

The loop currently has exactly one guard — `_apply_repeated_tool_call_guard`
in `ouro/core/loop/agent.py` — baked directly into the `TOOL_CALLS` branch. It
works (detects identical tool-call iterations, intercepts with feedback, hard
stops on runaway), but its shape is bespoke: a private method returning a
one-off `_RepeatGuardOutcome` NamedTuple, with `last_iter_sig` / `repeat_count`
threaded through the loop as local variables.

We want more checks of the same *kind*. Concrete near-term example: **only
allow the agent to modify a file it has previously read**. If the model issues
`write_file` / `edit` on a path it never `read_file`'d, block the call with a
deterministic error ("read the file first") instead of silently overwriting —
crucially, *before* the write runs. That rule needs to block one call before
dispatch (`before_toolcall`) and to learn which files were actually read from
real results (`after_toolcall`) — neither of which the bespoke guard can host.

Adding each new check as another private method + more threaded locals does not
scale and conflates distinct concerns inside one loop branch.

## Goals

- A first-class `Rule` abstraction in `ouro.core.loop`: deterministic,
  per-tool-call checks around dispatch.
- Block-before-dispatch (`before_toolcall`) so a side-effecting call (write /
  edit / delete) can be stopped before it runs — not merely reported after.
- Result rewrite / state capture after dispatch (`after_toolcall`).
- Per-call granularity: act on one call in a batch while siblings dispatch.
- Migrate the existing repeated-tool-call guard onto this abstraction. Rules
  only block or rewrite `tool_result`s — they never stop the run, so the old
  hard-stop is dropped (see Proposed Behavior); soft warnings are unchanged.
- Keep `ouro.core` tool-agnostic: the generic repeated-call rule lives in core;
  tool-aware rules (read-before-write) live in `ouro.capabilities`.

## Non-goals

- Implementing the read-before-write rule itself (follow-up PR; this RFC defines
  the seam and validates it mentally against that use case).
- A user-facing config surface for enabling/disabling individual rules (rules
  are wired in code via the Agent constructor / `AgentBuilder` for now).
- Any change to the `Hook` lifecycle (`on_run_start` / `on_iteration_start` /
  `on_iteration_end`). Rules are a separate concept from hooks.

## Proposed Behavior (User-Facing)

One intentional behavior change: the repeated-tool-call breaker's **hard stop is
removed**. A rule's only power is to block or rewrite a call's result, so when
the model repeats an identical call on consecutive turns past
`repeat_tool_call_threshold` the call keeps getting blocked with a "stop
repeating" warning every turn (soft intercept) but the run is no longer
terminated at a second threshold. Rationale: the warning is expected to redirect
the model; `Agent.max_iterations` remains the runaway backstop, and stopping the
loop is the loop's concern, not a rule's. The `repeat_tool_call_max` constructor
kwarg is therefore removed; `repeat_tool_call_threshold` is preserved (`<= 0`
still disables the check).

- CLI / UX changes: none.
- Config changes: `repeat_tool_call_max` kwarg removed (no external callers).
- Output / logging changes: soft-intercept warning unchanged in spirit (now
  per-call); no more hard-stop warning or "[ouro] Halted…" final answer.

## Invariants (Must Not Regress)

- Every `tool_call` still receives exactly one `tool_result` message (API
  requirement) — blocked calls get a synthetic result, dispatched calls a real
  one.
- Repeated-call soft intercept at `threshold` keeps its semantics, including the
  disabled-by-`<= 0` case.
- Assistant tool-call message is still persisted before any tool_result.
- Parallel/sequential dispatch batching is unchanged for non-blocked calls.
- Loop remains free of tool-name knowledge (`read_file`/`write_file` etc.).
- A rule cannot terminate the run; only the loop (STOP / LENGTH /
  `max_iterations`) ends it.

## Design Sketch (Minimal)

New module `ouro/core/loop/rules.py`. A rule is two **optional**, per-tool-call
hooks; it implements whichever it needs (the loop duck-types via `getattr`):

```python
@runtime_checkable
class Rule(Protocol):
    name: str
    # Before dispatch: return text to BLOCK the call (it is skipped and the
    # text becomes its tool_result), or None to let it run.
    def before_toolcall(self, ctx: LoopContext, tool_call: ToolCall) -> str | None: ...
    # After a dispatched call returns: return text to REPLACE its result, or
    # None to leave it. Also the place to record state from real results.
    def after_toolcall(self, ctx: LoopContext, tool_call: ToolCall,
                       tool_result: ToolResult) -> str | None: ...
```

No `RuleOutcome` / `RuleViolation` types and no `on_run_start`: rules return a
plain `str | None`, and per-run state self-resets where needed (see below).

`RepeatedToolCallRule(threshold)` (core, generic) implements only
`before_toolcall`: it tracks a per-`(name, arguments)` consecutive-iteration
count and, once a call recurs `threshold` times, blocks it with a "stop
repeating" message. State self-resets each run because `ctx.iteration` restarts
at 1 (stale counts are dropped) — no lifecycle reset method required. No hard
stop.

Loop integration (replaces the inline guard in the `TOOL_CALLS` branch):

1. After persisting the assistant tool-call message, run every rule's
   `before_toolcall` for each call; collect a `blocked: dict[id, str]` (messages
   from multiple rules blocking the same call are joined).
2. Dispatch only the non-blocked calls. For each dispatched call, run every
   rule's `after_toolcall` to (optionally) rewrite its result.
3. Append one `tool_result` per call in the model's original order — blocked
   text for blocked calls, (possibly rewritten) output for dispatched ones. If
   every call was blocked, dispatch nothing and `continue`.

`Agent.__init__` gains `rules: Sequence[Rule] = ()`; the `RepeatedToolCallRule`
(from `repeat_tool_call_threshold`) is always prepended, then caller rules.

Tool-aware rules (follow-up): `ReadBeforeWriteRule` in
`ouro/capabilities/rules/`, knowing the `read_file` / `write_file` / `edit`
tool names and their `file_path` arg; records read paths in `after_toolcall`,
blocks writes to unread paths in `before_toolcall`. Injected by `AgentBuilder`.
This respects the `interfaces → capabilities → core` import direction, and is
the motivating proof that `before_toolcall` must run *before* dispatch.

## Alternatives Considered

- **New `Hook` lifecycle method (`before_dispatch`)** instead of a separate
  `Rule` concept. Rejected: hooks are broad lifecycle/LLM-side effects
  (compaction, verification) that vote on continuation; rules are narrow
  deterministic per-call gates. Keeping them distinct keeps each contract small
  and the intent legible ("rule = formal check").
- **Leave the guard inline, add rules alongside.** Rejected: two parallel
  mechanisms doing the same thing in the same loop branch.
- **A single post-dispatch `observe`/`after_toolcall` (no before-hook).**
  Rejected: it runs after the call executed, so it cannot stop a side-effecting
  call (write/edit/delete) from happening — it can only rewrite what the model
  is told. Blocking such calls is the whole point of read-before-write, so a
  pre-dispatch `before_toolcall` is required.
- **`RuleOutcome`/`RuleViolation` value types + batch `check`.** Dropped in favor
  of per-call methods returning `str | None`: simpler, and the per-call shape
  matches how rules actually reason (about one call at a time).

## Test Plan

- Unit tests (new `test/test_loop_rules.py`):
  - `before_toolcall` blocks one call in a 2-call batch → blocked call gets the
    rule's text, sibling dispatches, loop continues.
  - `after_toolcall` rewrites a dispatched call's result (tool still runs).
  - A fully-blocked iteration still emits one tool_result per call and the run
    continues (no halt) until the model itself stops.
  - `after_toolcall` sees only dispatched calls, not blocked ones.
  - Multiple rules blocking the same call → text joined deterministically.
- Migrated coverage: `test/test_repeat_tool_call_circuit_breaker.py` drives
  `RepeatedToolCallRule` (per-call signature normalization, intercept at
  threshold, reset on changed args, disabled at `<= 0`, sustained repeats keep
  being intercepted without halting).
- Targeted: `./scripts/dev.sh test -q test/test_loop_rules.py
  test/test_repeat_tool_call_circuit_breaker.py test/test_parallel_tools.py
  test/test_ralph_loop.py`.
- `./scripts/dev.sh importlint` (boundary unchanged: rules stay in core).
- Smoke: `python main.py --task "say hi then stop" --verify`.

## Rollout / Migration

- Backward compatibility: `repeat_tool_call_threshold` kwarg preserved
  (`<= 0` still disables). `repeat_tool_call_max` is removed — it had no
  external callers (only `Agent` itself and its tests).
- Behavior change: the repeated-call hard stop is gone (see Proposed Behavior).
- Migration steps: none for callers. Internally, `_apply_repeated_tool_call_guard`
  and `_RepeatGuardOutcome` are removed; the per-call `_tool_call_signature`
  helper lives in `rules.py`.

## Risks & Mitigations

- **Losing the hard stop weakens runaway protection.** Mitigation: the soft
  warning still fires every repeat past `threshold`; capable models redirect on
  the warning, and `max_iterations` bounds the worst case. Accepted trade-off
  for a clean rule contract (rules replace results, never stop the loop).
- **Ordering / aggregation bugs when multiple rules block the same call.**
  Mitigation: deterministic aggregation (union by id, stable message order) with
  a dedicated unit test.
- **Layer leak (tool names creeping into core).** Mitigation: core rules use only
  `ToolCall`/`ToolResult`; tool-aware rules live in capabilities; importlint guards.

## Open Questions

- Should rule violations be surfaced to the `ProgressSink` (e.g. a
  `progress.info` line) so the user sees "blocked write_file: read it first"?
  Leaning yes in the follow-up, no extra surface in this PR.
- If a future check genuinely needs to *stop* the loop (not just warn), that
  belongs to the loop or a `Hook` vote, not the `Rule` contract — revisit then.
