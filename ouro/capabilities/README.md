# `ouro.capabilities` — Tools, Memory, Skills, Verification

The middle layer. Built on `ouro.core`. The canonical Python SDK most
users interact with.

## What's inside

```
ouro.capabilities
├── builder.py               # AgentBuilder + ComposedAgent (start here)
├── tools/                   # BaseTool + ToolExecutor + 13 builtins
│   ├── base.py
│   ├── executor.py          # implements ouro.core ToolRegistry
│   └── builtins/            # FileReadTool, ShellTool, GrepTool, …
├── memory/                  # MemoryManager + MemoryHook
│   ├── manager.py           # short/long-term + persistence
│   ├── compressor.py        # LLM-driven compaction
│   ├── long_term/           # ~/.ouro/memory/*.md daily notes
│   ├── store/               # YAML session persistence
│   └── hook.py              # MemoryHook (loop integration)
├── skills/                  # progressive-disclosure skill registry
├── verification/            # Verifier + LLMVerifier + VerificationHook (Ralph)
├── todo/                    # TodoList state
├── context/                 # platform/git/cwd context formatter
└── prompts/                 # DEFAULT_SYSTEM_PROMPT
```

## Public SDK

```python
from ouro.capabilities import (
    AgentBuilder,
    ComposedAgent,

    # Tools
    BaseTool,
    ToolExecutor,

    # Memory
    MemoryManager,
    MemoryHook,
    ShortTermMemory,
    WorkingMemoryCompressor,
    TokenTracker,
    LongTermMemoryManager,

    # Skills
    SkillsRegistry,
    SkillInfo,
    render_skills_section,

    # Verification
    Verifier,
    LLMVerifier,
    VerificationResult,
    VerificationHook,

    # Other
    TodoList,
    DEFAULT_SYSTEM_PROMPT,
    format_context_prompt,
)
```

Builtin tools are imported by name from
`ouro.capabilities.tools.builtins.*`:
`FileReadTool`, `FileWriteTool`, `GlobTool`, `GrepTool`, `ShellTool`,
`SmartEditTool`, `WebSearchTool`, `WebFetchTool`, `MultiTaskTool`,
`SendFileTool`, `CronTool`, `SessionManagerTool`, `TodoTool`,
`CodeStructureTool`.

## AgentBuilder

`AgentBuilder` is the canonical assembly path. Fluent `with_*` methods
configure pieces, `.build()` returns a fully wired `ComposedAgent`.

```python
import asyncio

from ouro.capabilities import AgentBuilder, SkillsRegistry
from ouro.capabilities.tools.builtins.file_ops import FileReadTool, FileWriteTool
from ouro.capabilities.tools.builtins.shell import ShellTool
from ouro.core.llm import LiteLLMAdapter, ModelManager

async def main() -> None:
    mm = ModelManager()
    profile = mm.get_current_model()
    llm = LiteLLMAdapter(
        model=profile.model_id,
        api_key=profile.api_key,
        api_base=profile.api_base,
    )

    skills = SkillsRegistry()
    await skills.load()

    agent = (
        AgentBuilder()
        .with_llm(llm, model_manager=mm)
        .with_max_iterations(20)
        .with_memory(sessions_dir=None, memory_dir=None)  # ~/.ouro defaults
        .with_skills(skills)
        .with_verification(max_iterations=3)              # Ralph outer loop
        .with_tools([FileReadTool(), FileWriteTool(), ShellTool()])
        .build()
    )

    print(await agent.run("Summarize the README in three bullet points."))

asyncio.run(main())
```

`TodoTool` is auto-injected on every build so the agent always has
`manage_todo_list`.

## ComposedAgent

`ComposedAgent` wraps `ouro.core.loop.Agent` and exposes back-compat
proxies the TUI/bot rely on.

For resumed-session UI, prefer these `ComposedAgent` helpers instead of
reaching into `agent.memory.short_term` directly. The loop owns transient
per-run messages; `MemoryHook`/`MemoryManager` own the persisted history
snapshot exposed here.

```python
agent.memory                 # MemoryManager (or None if .without_memory())
agent.tool_executor          # ToolExecutor (implements ToolRegistry)
agent.todo_list              # TodoList
agent.set_reasoning_effort("high")
agent.switch_model("anthropic/claude-3-5-sonnet-20241022")
await agent.load_session(session_id)
agent.get_memory_stats()
agent.get_session_messages()
agent.get_session_message_count()
agent.get_current_model_info()
```

`agent.run(task, *, verify=False, images=None)` handles:
- system prompt assembly (default + context + LTM + skills + soul) on
  the first turn,
- multimodal user message construction when `images` are provided,
- dispatch into the core loop, whose per-run message state is transient,
  while `MemoryHook` / `MemoryManager` own persisted conversation
  history when memory is enabled,
- placeholder substitution for image blocks before persistence so
  saved YAML sessions stay small,
- memory stats + flush at the end.

## Hooks

Two first-party hooks ship with this layer. Both are wired
automatically by `AgentBuilder`:

### MemoryHook

Adapts `MemoryManager` into the loop:

- `before_call`: substitutes the loop's transient message snapshot with
  `memory.get_context_for_llm()` and registers tool schemas for
  compaction accounting.
- UI/session-history consumers should treat that substituted context as an
  implementation detail and use `ComposedAgent.get_session_messages()` /
  `.get_session_message_count()` instead of reading memory internals.
- `after_call`: persists the assistant response with usage.
- `after_tool`: persists the tool result message.
- `on_compact_check`: returns `CompactionDecision` when memory says
  it needs compression; the cache-safe fork call is performed by the
  core loop.

### VerificationHook

Ralph-style outer loop:

- `on_run_start`: resets per-run state.
- `on_iteration_end(finished=True)`: runs the verifier; returns
  `STOP` if complete, `RETRY_WITH_FEEDBACK` if not, `STOP` once
  `max_iterations` is reached.

Bring your own verifier by passing `Verifier`-conforming objects:

```python
class MyVerifier:
    async def verify(self, task, result, iteration, previous_results):
        return VerificationResult(complete="DONE" in result.upper(), reason="")

builder.with_verification(max_iterations=3, verifier=MyVerifier())
```

## Adding a builtin tool

1. Subclass `BaseTool` under `tools/builtins/`. Implement `name`,
   `description`, `parameters`, and `async execute(**kwargs) -> str`.
   Set `readonly = True` if it doesn't mutate state — that unlocks
   parallel dispatch when multiple readonly tools fire in one turn.
2. Re-export from `ouro/capabilities/tools/__init__.py` if you want
   it on the public SDK.
3. Add to `ouro/interfaces/cli/factory.py` if it should ship in the
   default CLI/bot toolset.
4. Add a focused unit test under `test/`.

## Memory persistence

| Path | Format | Owner |
|---|---|---|
| `~/.ouro/sessions/<YYYY-MM-DD_uuid>/session.yaml` | YAML | `MemoryManager` |
| `~/.ouro/memory/memory.md` | Markdown | `LongTermMemoryManager` (durable) |
| `~/.ouro/memory/daily/YYYY-MM-DD.md` | Markdown | `LongTermMemoryManager` (rolling) |
| `~/.ouro/skills/<skill-name>/SKILL.md` | Markdown + frontmatter | `SkillsRegistry` |

Sessions persist incrementally on `add_message` and on `save_memory()`
flush; resuming is `await ComposedAgent.load_session(session_id)` or
`MemoryManager.from_session(session_id, llm, ...)`.

## See also

- [Capabilities layer agent instructions](CLAUDE.md) — rules for editing this layer.
- [Memory invariants](memory/CLAUDE.md) — serialization and compaction guarantees.
- [Tool contracts](tools/CLAUDE.md) — how to write a `BaseTool`.
- [Memory Management guide](../../docs/memory-management.md) — user-side memory model.
- [Extending guide](../../docs/extending.md) — adding tools, agents, providers.
- [Core layer README](../core/README.md) — what capabilities depends on.
