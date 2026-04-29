# `ouro.core` — Agent Loop + LLM Primitives

The bottom layer. Pure SDK with no UI dependencies. Depends only on
`litellm` and the standard library.

## What's inside

```
ouro.core
├── loop/                    # ReAct loop + hook protocol
│   ├── agent.py             # the Agent class
│   ├── message_list.py      # MessageList conversation-history wrapper
│   └── protocols.py         # Hook, ToolRegistry, ProgressSink, LoopContext
├── llm/                     # LiteLLM client + message types
│   ├── litellm_adapter.py   # LiteLLMAdapter
│   ├── message_types.py     # LLMMessage, LLMResponse, ToolCall, ToolResult
│   ├── model_manager.py     # ModelManager, ModelProfile
│   ├── reasoning.py         # reasoning_effort plumbing
│   ├── chatgpt_auth.py      # OAuth (ChatGPT Codex)
│   └── copilot_auth.py      # OAuth (GitHub Copilot)
├── runtime.py               # ~/.ouro/* path helpers
├── log.py                   # logger setup
└── model_pricing.py         # token cost lookups
```

## Public SDK

```python
from ouro.core import (
    # Loop
    Agent,
    MessageList,
    Hook,
    ToolRegistry,
    ProgressSink,
    NullProgressSink,
    LoopContext,
    CompactionDecision,
    ContinueDecision,
    ContinueKind,

    # LLM types
    LLMMessage,
    LLMResponse,
    ToolCall,
    ToolResult,
    ToolCallBlock,
    StopReason,

    # LLM client
    LiteLLMAdapter,
    ModelManager,
    ModelProfile,

    # Helpers
    REASONING_EFFORT_CHOICES,
    extract_text,
    get_runtime_dir,
    get_logger,
)
```

## Minimal usage — bare loop without memory or hooks

```python
import asyncio

from ouro.core.llm import LiteLLMAdapter, LLMMessage
from ouro.core.loop import Agent

class NoTools:
    def get_tool_schemas(self): return []
    def is_tool_readonly(self, name): return True
    async def execute_tool_call(self, name, arguments): raise NotImplementedError

async def main() -> None:
    llm = LiteLLMAdapter(model="openai/gpt-4o")
    agent = Agent(llm=llm, tools=NoTools())
    answer = await agent.run(
        task="Say hello",
        initial_messages=[LLMMessage(role="user", content="Say hello.")],
    )
    print(answer)

asyncio.run(main())
```

Most users won't construct `Agent` directly — they go through
`ouro.capabilities.AgentBuilder`, which wires memory, tools, and
verification hooks for you.

Internally, `Agent` now owns a mutable `MessageList` for per-run
conversation state instead of threading a bare Python list through loop
mutation sites. Hooks still receive ordinary `list[LLMMessage]`
snapshots so the hook protocol stays simple and serialization-friendly.

## The hook protocol

`Hook` is a structural Protocol. Every method is **optional**: the loop
resolves each call by `getattr(hook, name, None)`, so you only define
what you care about.

```python
class TimingHook:
    """Logs how long each LLM call takes."""

    async def before_call(self, ctx, messages, tools):
        ctx._t0 = time.monotonic()
        return messages

    async def after_call(self, ctx, response):
        elapsed = time.monotonic() - ctx._t0
        print(f"[iter {ctx.iteration}] LLM call: {elapsed:.2f}s")
        return response
```

| Method | When | Composition |
|---|---|---|
| `on_run_start(ctx, messages) -> messages` | Once before the first iteration | Chain (left-to-right, return value threads) |
| `before_call(ctx, messages, tools) -> messages` | Before every LLM call | Chain |
| `after_call(ctx, response) -> response` | After every LLM call | Chain |
| `before_tool(ctx, tool_call) -> tool_call` | Before each tool execution | Chain |
| `after_tool(ctx, tool_call, result) -> result` | After each tool execution | Chain |
| `on_compact_check(ctx, messages) -> CompactionDecision \| None` | Before each iteration | First non-None wins |
| `on_iteration_end(ctx, response, finished) -> ContinueDecision` | End of each iteration | `STOP` > `RETRY` > `CONTINUE`; multiple RETRY feedback messages are concatenated |
| `on_run_end(ctx, final_answer) -> None` | When the loop returns | Fan-out (side-effect only) |

## ToolRegistry

The loop never imports `BaseTool`. It only requires:

```python
class ToolRegistry(Protocol):
    def get_tool_schemas(self) -> list[dict[str, Any]]: ...
    def is_tool_readonly(self, name: str) -> bool: ...
    async def execute_tool_call(self, name: str, arguments: dict[str, Any]) -> str: ...
```

`ouro.capabilities.tools.executor.ToolExecutor` implements this. You
can plug in your own without depending on the capabilities layer.

## ProgressSink

UI-side rendering channel. Headless usage gets `NullProgressSink`
(no-op). The TUI provides `TuiProgressSink`. Capabilities never import
`terminal_ui` — they call into whatever sink they were given:

```python
class ProgressSink(Protocol):
    def info(self, msg: str) -> None: ...
    def thinking(self, text: str) -> None: ...
    def assistant_message(self, content: Any) -> None: ...
    def tool_call(self, name: str, arguments: dict[str, Any]) -> None: ...
    def tool_result(self, result: str) -> None: ...
    def final_answer(self, text: str) -> None: ...
    def unfinished_answer(self, text: str) -> None: ...
    def spinner(self, label: str, title: str | None = None) -> AbstractAsyncContextManager: ...
```

## Cache-safe compaction

Memory compaction is cache-safe by construction: when a hook returns
`CompactionDecision`, the loop appends the compaction prompt to the
current messages and calls the LLM **itself**, then hands the summary
back via `on_summary(...)`. Both the normal turn and the compaction
fork share the same system + tools prefix, so the provider's prompt
cache hits.

## See also

- [Core layer agent instructions](CLAUDE.md) — rules for editing the loop / LLM client.
- [LLM provider safety + timeouts](llm/CLAUDE.md).
- [Capabilities layer README](../capabilities/README.md) — the SDK most users start with.
