# ouro Package Layout (Three-Layer Architecture)

`AGENTS.md` is a symlink to this file.

The package is organized into three namespace subpackages with a strict
import direction enforced by `import-linter` (see `.importlinter` at
the repo root):

```
ouro.interfaces    →   ouro.capabilities   →   ouro.core
   (user-facing)        (built on core)        (loop + LLM primitives)
```

**Reverse imports are forbidden.** When you find yourself wanting one,
either invert the dependency, define a Protocol in the lower layer
that the higher layer satisfies structurally, or inject the value via
constructor.

## Layer responsibilities

### `ouro.core` — agent loop + LLM primitives
- Class-based ReAct loop (`Agent`) with optional Hooks.
- LLM types (`LLMMessage`, `LLMResponse`, `ToolCall`, `ToolResult`, …).
- LLM client (`LiteLLMAdapter`, `ModelManager`).
- Reasoning / runtime / log helpers.
- Public Protocols capabilities/interfaces implement: `Hook`,
  `ToolRegistry`, `ProgressSink`, `LoopContext`.

Never imports `ouro.capabilities` or `ouro.interfaces`. Never imports
`ouro.config` from `ouro.core.loop` (config is injected as constructor
arguments).

### `ouro.capabilities` — built on core
- Tools (BaseTool + builtins + ToolExecutor implementing ToolRegistry).
- Memory (MemoryManager + MemoryHook for the loop).
- Skills (registry, render, parser, installer).
- Verification (Verifier protocol + LLMVerifier + VerificationHook).
- Todo state, context env, prompts.
- `AgentBuilder` / `ComposedAgent` — the canonical assembly path.

Never imports `ouro.interfaces`. UI-side concerns (terminal_ui,
AsyncSpinner) are reached only through the injected `ProgressSink`.

### `ouro.interfaces` — user-facing
- CLI (argparse, factory, entry shim).
- TUI (interactive session, prompt_toolkit input, rich UI).
- Bot (lark/slack/wechat channels, webhook server, session router,
  cron scheduler).

Does not expose an SDK — only entry callables. Imports flow downward
into capabilities + core.

## Public SDK surfaces

- `ouro.core` re-exports loop primitives + LLM types.
- `ouro.capabilities` re-exports `AgentBuilder`, `ComposedAgent`, all
  builtin tools, memory, skills, verification.

## Where to put new code

| Concern                                    | Layer                |
|--------------------------------------------|----------------------|
| New stop reason / tool-call shape          | `ouro.core.llm`      |
| New LLM provider client                    | `ouro.core.llm`      |
| New Hook lifecycle method                  | `ouro.core.loop`     |
| New tool                                   | `ouro.capabilities.tools.builtins` |
| New memory strategy / compaction prompt    | `ouro.capabilities.memory`         |
| New skill type                             | `ouro.capabilities.skills`         |
| New verification rule                      | `ouro.capabilities.verification`   |
| New CLI flag / interactive command         | `ouro.interfaces.cli` / `ouro.interfaces.tui` |
| New bot channel                            | `ouro.interfaces.bot.channel`      |

## Verification

After non-trivial changes:
- `./scripts/dev.sh importlint` — boundary contracts.
- `./scripts/dev.sh test -q` — full test suite.
- `./scripts/dev.sh check` — bundles invariants + precommit + importlint
  + typecheck + tests.
