"""Loop-layer protocols.

The core loop never imports from `ouro.capabilities` or `ouro.interfaces`.
Capabilities (memory, tools, verification, …) plug into the loop by
implementing these structural Protocols.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ouro.core.llm import LLMMessage, LLMResponse, ToolOutput
    from ouro.core.loop.context import MessageListContext
    from ouro.core.loop.message_list import MessageList


@runtime_checkable
class ToolRegistry(Protocol):
    def get_tool_schemas(self) -> list[dict[str, Any]]: ...
    def is_tool_readonly(self, name: str) -> bool: ...
    def conflict_keys(self, name: str, arguments: dict[str, Any]) -> set[str] | None: ...
    async def execute_tool_call(self, name: str, arguments: dict[str, Any]) -> ToolOutput: ...


ProgressEventKind = Literal[
    "info",
    "thinking",
    "assistant_message",
    "tool_call",
    "tool_result",
    "tool_blocked",
    "task_list",
    "task_status",
    "swarm_reset",
    "swarm_header",
    "swarm_plan_item",
    "swarm_agent",
    "swarm_assignment",
    "swarm_status",
    "verification_status",
    "final_answer",
    "unfinished_answer",
    "session_loaded",
]


@dataclass(frozen=True)
class ProgressEvent:
    kind: ProgressEventKind
    payload: dict[str, Any] = field(default_factory=dict)


class _NullSpinner:
    async def __aenter__(self) -> _NullSpinner:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@runtime_checkable
class ProgressSink(Protocol):
    def emit(self, event: ProgressEvent) -> None: ...
    def spinner(self, label: str, title: str | None = None) -> AbstractAsyncContextManager[Any]: ...
    def on_session_loaded(self, messages: list[Any]) -> None: ...


class NullProgressSink:
    def emit(self, event: ProgressEvent) -> None:
        pass

    def spinner(self, label: str, title: str | None = None) -> AbstractAsyncContextManager[Any]:
        return _NullSpinner()

    def on_session_loaded(self, messages: list[Any]) -> None:
        pass


class LoopContext(Protocol):
    @property
    def task(self) -> str: ...
    @property
    def iteration(self) -> int: ...
    @property
    def usage_total(self) -> dict[str, int]: ...
    @property
    def stop_reason_last(self) -> str | None: ...
    @property
    def progress(self) -> ProgressSink: ...
    def add_usage(self, usage: dict[str, int] | None) -> None: ...


class _ContinueKind(str, Enum):
    STOP = "stop"
    CONTINUE = "continue"
    RETRY = "retry"


@dataclass(frozen=True)
class ContinueDecision:
    kind: _ContinueKind
    feedback_messages: tuple[LLMMessage, ...] = field(default_factory=tuple)

    @classmethod
    def stop(cls) -> ContinueDecision:
        return cls(kind=_ContinueKind.STOP)

    @classmethod
    def cont(cls) -> ContinueDecision:
        return cls(kind=_ContinueKind.CONTINUE)

    @classmethod
    def retry_with_feedback(cls, *messages: LLMMessage) -> ContinueDecision:
        return cls(kind=_ContinueKind.RETRY, feedback_messages=tuple(messages))


ContinueKind = _ContinueKind


@runtime_checkable
class Hook(Protocol):
    """Lifecycle hooks the agent loop dispatches.

    Three integration points:

    - ``on_run_start`` — once at the start of ``Agent.run``.
      Pure fanout (all hooks run, no return value).
    - ``on_iteration_start`` — at the top of every iteration *before*
      the LLM call.  Pure fanout.  Hooks may mutate ``context`` in
      place; the loop continues with the mutated state this same
      iteration.  Used by ``CompactionHook`` to compress
      ``context.detached`` when token usage gets close to the limit.
    - ``on_iteration_end`` — after the LLM returns ``STOP``.  Hooks
      vote ``ContinueDecision.stop()`` / ``cont()`` /
      ``retry_with_feedback(...)``; the loop aggregates with
      STOP > RETRY > CONTINUE.  Used by ``VerificationHook``.
    """

    async def on_run_start(self, ctx: LoopContext, messages: MessageList) -> None: ...
    async def on_iteration_start(
        self,
        ctx: LoopContext,
        context: MessageListContext,
        tools: list[dict[str, Any]],
    ) -> None: ...
    async def on_iteration_end(
        self,
        ctx: LoopContext,
        messages: MessageList,
        response: LLMResponse,
        finished: bool,
    ) -> ContinueDecision: ...
