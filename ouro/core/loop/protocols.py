"""Loop-layer protocols.

The core loop never imports from `ouro.capabilities` or `ouro.interfaces`.
Capabilities (memory, tools, verification, …) plug into the loop by
implementing these structural Protocols.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

if TYPE_CHECKING:
    from ouro.core.llm import LLMMessage, LLMResponse, ToolCall, ToolResult


# ---------------------------------------------------------------------------
# Tool registry — the only abstraction the loop needs over BaseTool.
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolRegistry(Protocol):
    """What `core.loop.Agent` requires from a tool registry.

    The capabilities layer's `ToolExecutor` implements this without any
    coupling back into core.
    """

    def get_tool_schemas(self) -> List[Dict[str, Any]]: ...
    def is_tool_readonly(self, name: str) -> bool: ...
    async def execute_tool_call(self, name: str, arguments: Dict[str, Any]) -> str: ...


# ---------------------------------------------------------------------------
# ProgressSink — optional UI-side channel for spinners / printed events.
# ---------------------------------------------------------------------------


class _NullSpinner:
    """No-op async context manager used as the default ProgressSink spinner."""

    async def __aenter__(self) -> "_NullSpinner":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@runtime_checkable
class ProgressSink(Protocol):
    """Optional UI sink injected by interfaces.

    All methods have safe no-op defaults so memoryless/headless usage
    needs no implementation. Capabilities never construct or import
    a TUI/terminal_ui — they call into the sink they were given.
    """

    def info(self, msg: str) -> None: ...
    def thinking(self, text: str) -> None: ...
    def assistant_message(self, content: Any) -> None: ...
    def tool_call(self, name: str, arguments: Dict[str, Any]) -> None: ...
    def tool_result(self, result: str) -> None: ...
    def final_answer(self, text: str) -> None: ...
    def unfinished_answer(self, text: str) -> None: ...

    def spinner(
        self, label: str, title: Optional[str] = None
    ) -> AbstractAsyncContextManager[Any]: ...


class NullProgressSink:
    """Concrete no-op ProgressSink. Use when no UI is wired up."""

    def info(self, msg: str) -> None: pass
    def thinking(self, text: str) -> None: pass
    def assistant_message(self, content: Any) -> None: pass
    def tool_call(self, name: str, arguments: Dict[str, Any]) -> None: pass
    def tool_result(self, result: str) -> None: pass
    def final_answer(self, text: str) -> None: pass
    def unfinished_answer(self, text: str) -> None: pass

    def spinner(
        self, label: str, title: Optional[str] = None
    ) -> AbstractAsyncContextManager[Any]:
        return _NullSpinner()


# ---------------------------------------------------------------------------
# LoopContext — read-only view passed to hooks each iteration.
# ---------------------------------------------------------------------------


class LoopContext(Protocol):
    """Read-only view of loop state. Hooks may inspect; the loop owns mutation."""

    @property
    def task(self) -> str: ...
    @property
    def iteration(self) -> int: ...
    @property
    def usage_total(self) -> Dict[str, int]: ...
    @property
    def stop_reason_last(self) -> Optional[str]: ...
    @property
    def progress(self) -> ProgressSink: ...


# ---------------------------------------------------------------------------
# Decision objects returned from specialty hooks.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompactionDecision:
    """Returned by `on_compact_check` to request a cache-safe compaction fork.

    The loop appends `compaction_prompt` to the current messages, calls the
    LLM (sharing the cached prefix), then invokes `on_summary` with the
    text and usage of the compaction call.
    """

    compaction_prompt: "LLMMessage"
    on_summary: Callable[[str, Dict[str, int]], Awaitable[None] | None]


class _ContinueKind(str, Enum):
    STOP = "stop"
    CONTINUE = "continue"
    RETRY = "retry"


@dataclass(frozen=True)
class ContinueDecision:
    kind: _ContinueKind
    feedback_messages: tuple["LLMMessage", ...] = field(default_factory=tuple)

    @classmethod
    def stop(cls) -> "ContinueDecision":
        return cls(kind=_ContinueKind.STOP)

    @classmethod
    def cont(cls) -> "ContinueDecision":
        return cls(kind=_ContinueKind.CONTINUE)

    @classmethod
    def retry_with_feedback(cls, *messages: "LLMMessage") -> "ContinueDecision":
        return cls(kind=_ContinueKind.RETRY, feedback_messages=tuple(messages))


# Re-exported as the "public" enum for `kind` comparison.
ContinueKind = _ContinueKind


# ---------------------------------------------------------------------------
# Hook protocol — every method optional (resolved via getattr).
# ---------------------------------------------------------------------------


@runtime_checkable
class Hook(Protocol):
    """Loop hook interface.

    Every method is optional. `Agent` resolves each call by `getattr(hook,
    name, None)`, so a hook implementation only defines the methods it
    cares about. Composition rules per method:

    - on_run_start, before_call, after_call, before_tool, after_tool:
        chained left-to-right; each hook's return value feeds the next.
    - on_compact_check: first hook returning non-None wins.
    - on_iteration_end: all hooks run; precedence STOP > RETRY > CONTINUE;
        multiple RETRY messages are concatenated in hook order.
    - on_run_end: all hooks run; side-effect only.
    """

    async def on_run_start(
        self, ctx: LoopContext, messages: List["LLMMessage"]
    ) -> List["LLMMessage"]: ...

    async def on_run_end(self, ctx: LoopContext, final_answer: str) -> None: ...

    async def before_call(
        self,
        ctx: LoopContext,
        messages: List["LLMMessage"],
        tools: List[Dict[str, Any]],
    ) -> List["LLMMessage"]: ...

    async def after_call(
        self, ctx: LoopContext, response: "LLMResponse"
    ) -> "LLMResponse": ...

    async def before_tool(
        self, ctx: LoopContext, tool_call: "ToolCall"
    ) -> "ToolCall": ...

    async def after_tool(
        self,
        ctx: LoopContext,
        tool_call: "ToolCall",
        result: "ToolResult",
    ) -> "ToolResult": ...

    async def on_compact_check(
        self, ctx: LoopContext, messages: List["LLMMessage"]
    ) -> Optional[CompactionDecision]: ...

    async def on_iteration_end(
        self,
        ctx: LoopContext,
        response: "LLMResponse",
        finished: bool,
    ) -> ContinueDecision: ...
