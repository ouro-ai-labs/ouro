# `ouro.core` — Agent Loop + LLM Primitives

The bottom layer. Pure SDK with no UI dependencies. Depends only on
`litellm` and the standard library.

## What's inside

```
ouro.core
├── loop/                    # ReAct loop + hook protocol
│   ├── agent.py             # the Agent class
│   ├── context.py           # MessageListContext (system + detached) + RunStatistic
│   ├── message_list.py      # mutable wrapper backing MessageListContext.detached
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
    Hook,
    ToolRegistry,
    ProgressSink,
    NullProgressSink,
    LoopContext,
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

# MessageList / MessageListContext / RunStatistic live one level deeper:
from ouro.core.loop import MessageList, MessageListContext, RunStatistic
```

## Minimal usage — bare loop without memory or hooks

```python
import asyncio

from ouro.core.llm import LiteLLMAdapter, LLMMessage
from ouro.core.loop import Agent, MessageListContext

class NoTools:
    def get_tool_schemas(self): return []
    def is_tool_readonly(self, name): return True
    async def execute_tool_call(self, name, arguments): raise NotImplementedError

async def main() -> None:
    llm = LiteLLMAdapter(model="openai/gpt-4o")
    agent = Agent(llm=llm, tools=NoTools())

    # Caller owns the conversation state; pass it in via ``context=``.
    # Persists across multiple ``agent.run(...)`` calls for multi-turn.
    ctx = MessageListContext()
    ctx.add_system_message(LLMMessage(role="system", content="Be brief."))
    ctx.detached.append(LLMMessage(role="user", content="Say hello."))

    answer = await agent.run("Say hello", context=ctx)
    print(answer)

asyncio.run(main())
```

Most users won't construct `Agent` directly — they go through
`ouro.capabilities.AgentBuilder`, which wires tools, compaction, and
verification hooks plus owns the `MessageListContext` for you.

`MessageListContext` is the canonical conversation store: a fixed
`system_messages` list + a mutable `detached: MessageList`. The loop
appends assistant + tool-result messages to `detached` directly each
iteration; hooks observe and may mutate it.

## The hook protocol

`Hook` is a structural Protocol. Every method is **optional**: the loop
resolves each call by `getattr(hook, name, None)`, so you only define
what you care about. Don't *inherit* from `Hook` — Protocol method
bodies (`...`) resolve to `return None` at runtime, which silently
clobbers the chain semantics for hooks that vote on a return value.

```python
import time

class TimingHook:
    """Logs how long each iteration takes."""

    async def on_iteration_start(self, ctx, context, tools):
        ctx._t0 = time.monotonic()

    async def on_iteration_end(self, ctx, messages, response, finished):
        from ouro.core.loop import ContinueDecision
        elapsed = time.monotonic() - ctx._t0
        print(f"[iter {ctx.iteration}] {elapsed:.2f}s")
        return ContinueDecision.cont()
```

| Method | When | Composition |
|---|---|---|
| `on_run_start(ctx, messages) -> None` | Once before the first iteration | Fanout (side-effect only) |
| `on_iteration_start(ctx, context, tools) -> None` | Top of every iteration, before the LLM call | Fanout. Hooks may mutate `context.system_messages` and `context.detached` in place; the loop runs the LLM call on whatever state hooks leave behind. Used by `CompactionHook` to compress mid-iteration. |
| `on_iteration_end(ctx, messages, response, finished) -> ContinueDecision` | After the LLM returns `STOP` | `STOP` > `RETRY` > `CONTINUE`; multiple RETRY feedback messages are concatenated. Used by `VerificationHook`. |

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

Compaction is owned end-to-end by `CompactionHook` (in
`ouro.capabilities.compaction`). On `on_iteration_start` the hook:

1. Snapshots `context.detached`, estimates tokens, and decides
   whether to compress.
2. If yes, builds a **cache-safe fork**: `system_messages +
   detached + compaction_prompt`. The fork reuses the live
   system prefix so the provider's prompt cache stays hot for
   both this LLM call and the regular call the loop issues
   right after.
3. Runs its own LLM call to produce the summary, calls
   `apply_compression(...)`, and replaces `context.detached`
   in place.
4. Returns. The loop then runs its **normal** LLM call this same
   iteration with the compressed history — no extra round trip.

The core loop knows nothing about compaction; any future
"intervene before the LLM call" hook plugs in the same way.

## See also

- [Core layer agent instructions](CLAUDE.md) — rules for editing the loop / LLM client.
- [LLM provider safety + timeouts](llm/CLAUDE.md).
- [Capabilities layer README](../capabilities/README.md) — the SDK most users start with.
