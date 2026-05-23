# ouro.core — Agent Loop + LLM Primitives

`AGENTS.md` is a symlink to this file.

The bottom layer. Depends on `litellm` and the standard library only.
Never imports `ouro.capabilities` or `ouro.interfaces`.

## What lives here

- `loop/agent.py` — `Agent` class (the ReAct loop). Iteration
  count, parallel/sequential tool dispatch, STOP / TOOL_CALLS /
  LENGTH branching. No knowledge of memory, BaseTool, Verifier,
  Config, or terminal_ui.
- `loop/context.py` — `MessageListContext` (system messages +
  mutable `detached: MessageList`) and `RunStatistic` (per-run
  iteration / token / stop-reason counters). The loop owns the
  conversation list; capability hooks observe and mutate it.
- `loop/message_list.py` — thin mutable wrapper used inside
  `MessageListContext.detached`.
- `loop/protocols.py` — structural Protocols capabilities implement:
  `Hook`, `ToolRegistry`, `ProgressSink`, `LoopContext`. Plus the
  `ContinueDecision` return type used by `on_iteration_end`.
- `loop/rules.py` — `Rule` protocol + `RuleOutcome` / `RuleViolation`
  and the generic `RepeatedToolCallRule`. Rules are deterministic
  pre-dispatch guards; see "Rules" below.
- `llm/` — `LLMMessage`, `LLMResponse`, `ToolCall`, `ToolResult`,
  `LiteLLMAdapter`, `ModelManager`, content/compat/reasoning helpers,
  OAuth (chatgpt, copilot).
- `runtime.py`, `log.py`, `model_pricing.py` — small shared helpers.

## Editing the loop

If you change `loop/agent.py`:

- Update or add tests against `core.loop.Agent` directly with a stub
  LLM and a fake `ToolRegistry`. Do **not** reach into private methods
  from interfaces or capabilities tests.
- Run `./scripts/dev.sh test -q test/test_parallel_tools.py
  test/test_reasoning_effort.py test/test_ralph_loop.py`.
- Do a real smoke: `python -m ouro.interfaces.cli.entry --task "<…>"`.

## Async/runtime rules

- No blocking I/O in `loop/agent.py` or `llm/`. Prefer native async; if
  unavoidable, use `asyncio.to_thread` with timeouts and cancellation.
- Don't call `asyncio.run()` from library code.

## Adding a new Hook lifecycle method

The current protocol carries three methods: `on_run_start`,
`on_iteration_start`, `on_iteration_end`. Lifecycle methods are
added on demand — keep dead extension points out.

1. Define the method on the `Hook` Protocol in `protocols.py`.
2. Add a dispatcher in `agent.py` (`_fanout_async` for side-effect
   hooks, `_aggregate_continue`-style for hooks that vote on a
   decision; chain helpers were removed when the methods that used
   them stopped having any implementer).
3. Update first-party hooks in
   `ouro.capabilities.{compaction,verification}.hook` to implement
   it (skip if irrelevant — Protocol is structural, missing methods
   are fine).
4. Update `ouro/core/README.md` and `ouro/CLAUDE.md` if the
   contract for hook composition changes.

## Rules (deterministic pre-dispatch guards)

`Rule` (`loop/rules.py`) is a separate extension point from `Hook`: a
deterministic check the loop runs over the model's proposed tool calls
*before* dispatch. A rule blocks individual calls — the loop substitutes
its feedback message as that call's `tool_result` so the model
self-corrects next turn — trading a probabilistic LLM mistake for a
deterministic guarantee. A rule **only replaces results; it never stops
the loop** (runaway protection is the loop's job via `max_iterations`).
See `rfc/loop-rules.md`.

- Contract: `on_run_start()` (reset per-run state), `check(ctx,
  tool_calls) -> RuleOutcome` (which calls to block; no LLM/I/O),
  `observe(ctx, executed)` (post-dispatch state update from real results).
- The loop aggregates all rules in `Agent._apply_rules` (union of blocked
  ids), dispatches only unblocked calls, then appends one `tool_result`
  per call in the model's original order (synthetic for blocked, real for
  dispatched).
- Core rules stay tool-agnostic (only `ToolCall`/`ToolResult`).
  `RepeatedToolCallRule` ships on by default (governed by
  `repeat_tool_call_threshold`; warns on repeats, never halts). Tool-aware
  rules (e.g. read-before-write) belong in `ouro.capabilities` and are
  injected via the Agent `rules=` arg / `AgentBuilder`.
