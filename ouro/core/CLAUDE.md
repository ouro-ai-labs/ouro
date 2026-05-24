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
- `loop/rules.py` — `Rule` protocol (optional `before_toolcall` /
  `after_toolcall`) + the generic `RepeatedToolCallRule`. Rules are
  deterministic per-tool-call checks; see "Rules" below.
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

## Rules (deterministic per-tool-call checks)

`Rule` (`loop/rules.py`) is a separate extension point from `Hook`: a
deterministic check the loop runs *around each individual tool call*. A
rule **only blocks or rewrites a call's result; it never stops the loop**
(runaway protection is the loop's job via `max_iterations`). See
`rfc/loop-rules.md`.

- Contract — two optional methods, the loop duck-types via `getattr`:
  - `before_toolcall(ctx, tool_call) -> str | None`: runs before dispatch;
    return text to **block** the call (it is skipped and the text becomes
    its `tool_result`), or `None` to let it run. This is the only way to
    stop a side-effecting call (write/edit/delete) from happening.
  - `after_toolcall(ctx, tool_call, tool_result) -> str | None`: runs after
    a dispatched call; return text to **replace** its result, `None` to
    leave it. Also the place to record state from real results.
- No LLM/I/O in either; both are per-tool-call. The loop runs all
  `before_toolcall`s (`Agent._rules_before`), dispatches only unblocked
  calls, runs `after_toolcall`s (`Agent._rules_after`), then appends one
  `tool_result` per call in the model's original order.
- Core rules stay tool-agnostic (only `ToolCall`/`ToolResult`).
  `RepeatedToolCallRule` ships on by default (governed by
  `repeat_tool_call_threshold`; warns on repeats via `before_toolcall`,
  never halts; self-resets per run via `ctx.iteration`). Tool-aware rules
  (e.g. read-before-write) belong in `ouro.capabilities` and are injected
  via the Agent `rules=` arg / `AgentBuilder`.
