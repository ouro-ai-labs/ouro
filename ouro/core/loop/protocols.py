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
    Protocol,
    runtime_checkable,
)

if TYPE_CHECKING:
    from ouro.core.llm import LLMMessage, LLMResponse, ToolCall, ToolResult
    from ouro.core.loop.message_list import MessageList


@runtime_checkable
class ToolRegistry(Protocol):
    def get_tool_schemas(self) -> list[dict[str, Any]]: ...
    def is_tool_readonly(self, name: str) -> bool: ...
    async def execute_tool_call(self, name: str, arguments: dict[str, Any]) -> str: ...


class _NullSpinner:
    async def __aenter__(self) -> _NullSpinner:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@runtime_checkable
class ProgressSink(Protocol):
    def info(self, msg: str) -> None: ...
    def thinking(self, text: str) -> None: ...
    def assistant_message(self, content: Any) -> None: ...
    def tool_call(self, name: str, arguments: dict[str, Any]) -> None: ...
    def tool_result(self, result: str) -> None: ...
    def final_answer(self, text: str) -> None: ...
    def unfinished_answer(self, text: str) -> None: ...
    def spinner(self, label: str, title: str | None = None) -> AbstractAsyncContextManager[Any]: ...


class NullProgressSink:
    def info(self, msg: str) -> None:
        pass

    def thinking(self, text: str) -> None:
        pass

    def assistant_message(self, content: Any) -> None:
        pass

    def tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        pass

    def tool_result(self, result: str) -> None:
        pass

    def final_answer(self, text: str) -> None:
        pass

    def unfinished_answer(self, text: str) -> None:
        pass

    def spinner(self, label: str, title: str | None = None) -> AbstractAsyncContextManager[Any]:
        return _NullSpinner()


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


@dataclass(frozen=True)
class CompactionDecision:
    compaction_prompt: LLMMessage
    on_summary: Callable[[str, dict[str, int], MessageList], Awaitable[None] | None]


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
    async def on_run_start(self, ctx: LoopContext, messages: MessageList) -> None: ...
    async def on_run_end(
        self,
        ctx: LoopContext,
        messages: MessageList,
        final_answer: str,
    ) -> None: ...
    async def before_call(
        self,
        ctx: LoopContext,
        messages: MessageList,
        tools: list[dict[str, Any]],
    ) -> list[LLMMessage]: ...
    async def after_call(
        self,
        ctx: LoopContext,
        messages: MessageList,
        response: LLMResponse,
    ) -> LLMResponse: ...
    async def before_tool(self, ctx: LoopContext, tool_call: ToolCall) -> ToolCall: ...
    async def after_tool(
        self,
        ctx: LoopContext,
        tool_call: ToolCall,
        result: ToolResult,
    ) -> ToolResult: ...
    async def on_tool_results(
        self,
        ctx: LoopContext,
        messages: MessageList,
        calls: list[ToolCall],
        results: list[ToolResult],
    ) -> None: ...
    async def on_compact_check(
        self,
        ctx: LoopContext,
        messages: MessageList,
    ) -> CompactionDecision | None: ...
    async def on_iteration_end(
        self,
        ctx: LoopContext,
        messages: MessageList,
        response: LLMResponse,
        finished: bool,
    ) -> ContinueDecision: ...
