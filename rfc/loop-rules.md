# RFC: Loop Rules (Deterministic Pre-Dispatch Guards)

- Status: Draft
- Authors: Yixin Luo
- Date: 2026-05-23

## Summary

Generalize the hard-coded repeated-tool-call guard in the core agent loop into
a pluggable **Rule** abstraction: a small set of deterministic, formal checks
that run over the model's proposed tool calls *before* dispatch and block
individual calls — substituting the rule's feedback as that call's synthetic
`tool_result` so the model self-corrects. A rule never stops the loop; it only
replaces results. Rules trade a probabilistic LLM mistake for a deterministic
guarantee.

## Problem

The loop currently has exactly one guard — `_apply_repeated_tool_call_guard`
in `ouro/core/loop/agent.py` — baked directly into the `TOOL_CALLS` branch. It
works (detects identical tool-call iterations, intercepts with feedback, hard
stops on runaway), but its shape is bespoke: a private method returning a
one-off `_RepeatGuardOutcome` NamedTuple, with `last_iter_sig` / `repeat_count`
threaded through the loop as local variables.

We want more checks of the same *kind*. Concrete near-term example: **only
allow the agent to modify a file it has previously read**. If the model issues
`write_file` / `edit` on a path it never `read_file`'d, return a deterministic
error ("read the file first") instead of silently overwriting. This is exactly
the repeated-call pattern — inspect proposed tool calls, decide deterministically,
feed the verdict back as a `tool_result` so the model self-corrects — but it
needs per-call granularity and per-run state that the current bespoke guard
can't host.

Adding each new check as another private method + more threaded locals does not
scale and conflates distinct concerns inside one loop branch.

## Goals

- A first-class `Rule` abstraction in `ouro.core.loop`: deterministic checks
  evaluated before tool dispatch.
- Per-tool-call granularity: a rule can block one call in a batch while letting
  siblings dispatch.
- Per-run rule state with a reset hook, and a post-dispatch `observe` hook so
  stateful rules (e.g. "files I've read") can update from real results.
- Migrate the existing repeated-tool-call guard onto this abstraction. Rules
  only replace `tool_result`s — they never stop the run, so the old hard-stop
  is dropped (see Proposed Behavior); soft warnings are unchanged.
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
removed**. A rule's only power is to replace tool_results, so when the model
repeats an identical batch past `repeat_tool_call_threshold` it keeps getting a
"stop repeating" warning every turn (soft intercept, unchanged) but the run is
no longer terminated at a second threshold. Rationale: the warning is expected
to redirect the model; `Agent.max_iterations` remains the runaway backstop, and
stopping the loop is the loop's concern, not a rule's. The
`repeat_tool_call_max` constructor kwarg is therefore removed;
`repeat_tool_call_threshold` is preserved (`<= 0` still disables the check).

- CLI / UX changes: none.
- Config changes: `repeat_tool_call_max` kwarg removed (no external callers).
- Output / logging changes: soft-intercept warning unchanged; no more hard-stop
  warning or "[ouro] Halted…" final answer.

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

New module `ouro/core/loop/rules.py`:

```python
@dataclass(frozen=True)
class RuleViolation:
    tool_call_id: str
    message: str            # becomes the synthetic tool_result content

@dataclass(frozen=True)
class RuleOutcome:
    violations: tuple[RuleViolation, ...] = ()   # calls to block; no halt power

@runtime_checkable
class Rule(Protocol):
    name: str
    def on_run_start(self) -> None: ...                       # reset per-run state
    def check(self, ctx: LoopContext,
              tool_calls: list[ToolCall]) -> RuleOutcome: ...  # pre-dispatch verdict
    def observe(self, ctx: LoopContext,
                executed: list[tuple[ToolCall, ToolResult]]) -> None: ...  # post-dispatch
```

`RepeatedToolCallRule(threshold)` (core, generic) ports the soft-intercept half
of the old guard: holds `last_iter_sig` / `repeat_count`; `check` returns all
calls as violations once the count reaches `threshold` (the model is warned and
the calls are not dispatched). It has no hard stop.

Loop integration (replaces the inline guard in the `TOOL_CALLS` branch):

1. `on_run_start`: call `rule.on_run_start()` for each rule (alongside hook
   fanout).
2. After persisting the assistant tool-call message, run every rule's `check`
   and aggregate: union violations by `tool_call_id` (concatenate messages from
   multiple rules that block the same call) into a `blocked: dict[id, str]`.
3. Dispatch only the non-blocked calls. Build `contents` = blocked feedback
   merged with dispatched results, then append one `tool_result` per call in the
   model's original order. If every call was blocked, dispatch nothing and just
   `continue` to the next turn.
4. `observe` all rules with the executed `(ToolCall, ToolResult)` pairs.

`Agent.__init__` gains `rules: Sequence[Rule] = ()`; the `RepeatedToolCallRule`
(from `repeat_tool_call_threshold`) is always prepended, then caller rules.

Tool-aware rules (follow-up): `ReadBeforeWriteRule` in
`ouro/capabilities/rules/`, knowing the `read_file` / `write_file` / `edit`
tool names and their `file_path` arg; tracks read paths in `observe`, blocks
writes to unread paths in `check`. Injected by `AgentBuilder`. This respects the
`interfaces → capabilities → core` import direction.

## Alternatives Considered

- **New `Hook` lifecycle method (`before_dispatch`)** instead of a separate
  `Rule` concept. Rejected: hooks are broad lifecycle/LLM-side effects
  (compaction, verification) that vote on continuation; rules are narrow
  deterministic per-call gates. Keeping them distinct keeps each contract small
  and the intent legible ("rule = formal check").
- **Leave the guard inline, add rules alongside.** Rejected: two parallel
  mechanisms doing the same thing in the same loop branch.
- **Whole-iteration verdict only (no per-call granularity).** Rejected: the
  read-before-write use case must block one call while dispatching siblings.

## Test Plan

- Unit tests (new `test/test_loop_rules.py`):
  - A toy `Rule` blocks one call in a 2-call batch → blocked call gets the
    synthetic message, sibling dispatches, loop continues.
  - A fully-blocked iteration still emits one tool_result per call and the run
    continues (no halt) until the model itself stops.
  - `on_run_start` resets state across two `run()` calls.
  - `observe` receives only the dispatched `(ToolCall, ToolResult)` pairs.
  - Multiple rules blocking the same call → feedback joined deterministically.
- Migrated coverage: `test/test_repeat_tool_call_circuit_breaker.py` updated to
  drive `RepeatedToolCallRule` (signature normalization, intercept at threshold,
  reset on changed args, disabled at `<= 0`, and sustained repeats keep being
  intercepted without halting).
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
  and `_RepeatGuardOutcome` are removed; `_tool_call_iter_signature` moves into
  `rules.py`.

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
