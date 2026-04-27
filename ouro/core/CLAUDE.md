# ouro.core — Agent Loop + LLM Primitives

`AGENTS.md` is a symlink to this file.

The bottom layer. Depends on `litellm` and the standard library only.
Never imports `ouro.capabilities` or `ouro.interfaces`.

## What lives here

- `loop/agent.py` — `Agent` class (the ReAct loop). Iteration count,
  parallel/sequential tool dispatch, cache-safe compaction fork,
  STOP/TOOL_CALLS branching. No knowledge of memory, BaseTool,
  Verifier, Config, or terminal_ui.
- `loop/protocols.py` — structural Protocols capabilities implement:
  `Hook`, `ToolRegistry`, `ProgressSink`, `LoopContext`. Plus return
  types `CompactionDecision`, `ContinueDecision`.
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

1. Define the method on the `Hook` Protocol in `protocols.py`.
2. Add a chain/aggregate dispatcher in `agent.py`.
3. Update `ouro/CLAUDE.md` if the contract for hook composition changes.
4. Update first-party hooks in `ouro.capabilities.{memory,verification}.hook`
   to implement (or skip) the new method.
