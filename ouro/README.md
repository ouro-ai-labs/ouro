# `ouro` — Package Architecture

Ouro is organized into three namespace subpackages. Imports flow downward
only; reverse imports are forbidden and enforced by `import-linter`
(see `.importlinter` at repo root).

```
ouro.interfaces   user-facing: CLI / TUI / bot         no SDK
       ↓
ouro.capabilities tools, memory, skills, verification  Python SDK
       ↓
ouro.core         agent loop + LLM primitives          Python SDK
```

## Layer guides

| Layer | What it gives you | Read |
|---|---|---|
| **`ouro.core`** | Agent loop class, hook protocol, LLM types, LiteLLM client | [ouro/core/README.md](core/README.md) |
| **`ouro.capabilities`** | `AgentBuilder` / `ComposedAgent`, builtin tools, memory hook, verification hook, skills | [ouro/capabilities/README.md](capabilities/README.md) |
| **`ouro.interfaces`** | CLI entry, interactive TUI, bot webhook server + channels | [ouro/interfaces/README.md](interfaces/README.md) |

## Picking the right layer for new code

- **Adding an LLM provider, a new stop reason, or a hook lifecycle method?**
  → `ouro.core`
- **Adding a tool, a memory strategy, a skill, or a verification rule?**
  → `ouro.capabilities`
- **Adding a CLI flag, a slash command, or a new bot channel?**
  → `ouro.interfaces`

## Boundary verification

```bash
./scripts/dev.sh importlint
# Contracts: 3 kept, 0 broken.
```

The contract:

1. `ouro.interfaces` → `ouro.capabilities` → `ouro.core` (downward only).
2. `ouro.core` may not import `ouro.capabilities`.
3. `ouro.capabilities` may not import `ouro.interfaces`.

UI side concerns reach capabilities through the
`ouro.core.loop.ProgressSink` Protocol (the TUI ships
`TuiProgressSink`; headless callers use `NullProgressSink`). The bot's
`CronScheduler` plugs into `ouro.capabilities.tools.builtins.cron_tool`
through a capability-local Protocol.

## SDK quickstart

```python
import asyncio

from ouro.capabilities import AgentBuilder
from ouro.capabilities.tools.builtins.shell import ShellTool
from ouro.core.llm import LiteLLMAdapter

async def main() -> None:
    agent = (
        AgentBuilder()
        .with_llm(LiteLLMAdapter(model="openai/gpt-4o"))
        .with_memory()
        .with_tool(ShellTool())
        .build()
    )
    print(await agent.run("List files in the current directory."))

asyncio.run(main())
```

For the `ouro` CLI itself, see the [root README](../README.md) and the
[CLI Guide](../docs/cli-guide.md).
