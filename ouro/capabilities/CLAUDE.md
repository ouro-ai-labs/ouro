# ouro.capabilities — Capabilities Layer

`AGENTS.md` is a symlink to this file.

The middle layer. Built on top of `ouro.core`. Provides the user-
facing Python SDK via `AgentBuilder` / `ComposedAgent` plus the
individual building blocks (tools, memory, skills, verification).
Never imports `ouro.interfaces` — UI side concerns are reached via
the injected `ProgressSink` Protocol from `ouro.core.loop`.

## Subpackages

- `tools/` — `BaseTool` interface, `ToolExecutor` (implements the
  core `ToolRegistry` Protocol), and 13 builtins under `builtins/`.
- `memory/` — `MemoryManager` + persistence + `MemoryHook`.
- `skills/` — registry, parser, render, installer, bundled system data.
- `verification/` — `Verifier` Protocol + `LLMVerifier` +
  `VerificationHook` (Ralph-style outer loop).
- `todo/`, `context/`, `prompts/` — small leaf utilities.
- `builder.py` — `AgentBuilder` (fluent construction) +
  `ComposedAgent` (core.Agent + convenience proxies).

## Safety rails

- Keep changes incremental; preserve existing behavior unless the
  task explicitly changes it. List behavior changes in the PR summary.
- No blocking I/O in the loop hot path (memory, tools, skills, verifier).
  Prefer native async; if unavoidable, use `asyncio.to_thread` with
  timeouts and cancellation.

## Editing memory / verification / hooks

- `MemoryHook` and `VerificationHook` are the only first-party hooks.
  Their composition with `core.loop.Agent` is described in
  `ouro/CLAUDE.md`.
- If you change compaction strategy or persistence shape, run
  `./scripts/dev.sh test -q test/memory/`.
- If you change the Ralph outer loop, run `./scripts/dev.sh test -q
  test/test_ralph_loop.py` and a real smoke
  `python -m ouro.interfaces.cli.entry --task "<…>" --verify`.

## Adding a new builtin tool

1. Drop the `BaseTool` subclass under `tools/builtins/`.
2. Re-export it from `ouro/capabilities/tools/__init__.py` if you
   want it on the public SDK; otherwise leave it for explicit imports.
3. Wire it into `ouro/interfaces/cli/factory.py` if it should be in
   the default CLI/bot toolset.
4. Add a focused unit test under `test/`.

## Adding a new hook

Implement the relevant `Hook` Protocol method(s) (defined in
`ouro.core.loop.protocols`). Don't subclass — Protocol is structural.
Pass it through `AgentBuilder.with_hook(...)`.
