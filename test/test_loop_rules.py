"""Tests for the per-tool-call Rule abstraction (ouro.core.loop.rules).

Covers the generic seam — ``before_toolcall`` blocking a call before dispatch,
``after_toolcall`` rewriting a dispatched call's result, both being optional,
and per-call granularity — independent of the repeated-tool-call rule (which
keeps its dedicated suite in ``test_repeat_tool_call_circuit_breaker.py``).
"""

from __future__ import annotations

import pytest

from ouro.capabilities.tools.base import BaseTool
from ouro.capabilities.tools.executor import ToolExecutor
from ouro.core.llm import LLMResponse, StopReason, ToolCall, ToolResult
from ouro.core.loop import Agent, MessageListContext, NullProgressSink


class _NoopTool(BaseTool):
    readonly = True

    def __init__(self, name: str) -> None:
        self._name = name
        self.invocations: int = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "stub"

    @property
    def parameters(self):
        return {}

    async def execute(self, **kwargs) -> str:
        self.invocations += 1
        return f"{self._name}-result"


class _ScriptedLLM:
    model = "stub-model"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def call_async(self, **kwargs) -> LLMResponse:
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="done", stop_reason=StopReason.STOP)

    def extract_text(self, response: LLMResponse) -> str:
        return response.content or ""

    def extract_tool_calls(self, response: LLMResponse) -> list[ToolCall]:
        return list(response.tool_calls or [])


def _tool_calls_response(*calls: tuple[str, str, dict]) -> LLMResponse:
    return LLMResponse(
        content=None,
        stop_reason=StopReason.TOOL_CALLS,
        tool_calls=[ToolCall(id=cid, name=name, arguments=args) for cid, name, args in calls],
    )


class _BlockToolRule:
    """before-only rule: blocks any call to a named tool, records the rest."""

    name = "block-tool"

    def __init__(self, tool_name: str, message: str) -> None:
        self._tool_name = tool_name
        self._message = message
        self.seen_after: list[tuple[str, str]] = []

    def before_toolcall(self, ctx, tool_call: ToolCall) -> str | None:
        return self._message if tool_call.name == self._tool_name else None

    def after_toolcall(self, ctx, tool_call: ToolCall, tool_result: ToolResult) -> str | None:
        # Record dispatched results (blocked calls never reach here); leave them.
        self.seen_after.append((tool_call.name, tool_result.content))
        return None


@pytest.mark.asyncio
async def test_before_blocks_one_call_and_dispatches_sibling():
    read_tool = _NoopTool("read_file")
    write_tool = _NoopTool("write_file")
    llm = _ScriptedLLM(
        [
            _tool_calls_response(
                ("c1", "write_file", {"file_path": "/x"}),
                ("c2", "read_file", {"file_path": "/y"}),
            ),
            LLMResponse(content="ok", stop_reason=StopReason.STOP),
        ]
    )
    rule = _BlockToolRule("write_file", "[test] read it before writing")
    agent = Agent(
        llm=llm,
        tools=ToolExecutor([read_tool, write_tool]),
        progress=NullProgressSink(),
        rules=[rule],
    )

    answer = await agent.run("test")

    assert answer == "ok"
    assert write_tool.invocations == 0  # blocked before dispatch
    assert read_tool.invocations == 1  # sibling dispatched
    # after_toolcall only sees the dispatched call, not the blocked one.
    assert rule.seen_after == [("read_file", "read_file-result")]


@pytest.mark.asyncio
async def test_blocked_call_feedback_reaches_history_in_order():
    read_tool = _NoopTool("read_file")
    write_tool = _NoopTool("write_file")
    ctx = MessageListContext()
    llm = _ScriptedLLM(
        [
            _tool_calls_response(
                ("c1", "write_file", {"file_path": "/x"}),
                ("c2", "read_file", {"file_path": "/y"}),
            ),
            LLMResponse(content="ok", stop_reason=StopReason.STOP),
        ]
    )
    agent = Agent(
        llm=llm,
        tools=ToolExecutor([read_tool, write_tool]),
        progress=NullProgressSink(),
        rules=[_BlockToolRule("write_file", "[test] blocked")],
    )

    await agent.run("test", context=ctx)

    tool_msgs = [m for m in ctx.detached.snapshot() if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["c1", "c2"]
    assert tool_msgs[0].content == "[test] blocked"
    assert tool_msgs[1].content == "read_file-result"


class _RewriteRule:
    """after-only rule: rewrites a named tool's result text."""

    name = "rewrite"

    def __init__(self, tool_name: str, replacement: str) -> None:
        self._tool_name = tool_name
        self._replacement = replacement

    def after_toolcall(self, ctx, tool_call: ToolCall, tool_result: ToolResult) -> str | None:
        return self._replacement if tool_call.name == self._tool_name else None


@pytest.mark.asyncio
async def test_after_rewrites_dispatched_result():
    """after_toolcall replaces a real result; the tool still runs."""
    read_tool = _NoopTool("read_file")
    ctx = MessageListContext()
    llm = _ScriptedLLM(
        [
            _tool_calls_response(("c1", "read_file", {"file_path": "/x"})),
            LLMResponse(content="ok", stop_reason=StopReason.STOP),
        ]
    )
    agent = Agent(
        llm=llm,
        tools=ToolExecutor([read_tool]),
        progress=NullProgressSink(),
        rules=[_RewriteRule("read_file", "[test] rewritten")],
    )

    await agent.run("test", context=ctx)

    assert read_tool.invocations == 1  # rewrite happens after real dispatch
    tool_msgs = [m for m in ctx.detached.snapshot() if m.role == "tool"]
    assert tool_msgs[0].content == "[test] rewritten"


class _BlockAllRule:
    name = "block-all"

    def before_toolcall(self, ctx, tool_call: ToolCall) -> str | None:
        return "[test] blocked"


@pytest.mark.asyncio
async def test_fully_blocked_iteration_continues_without_dispatch():
    read_tool = _NoopTool("read_file")
    ctx = MessageListContext()
    llm = _ScriptedLLM(
        [
            _tool_calls_response(("c1", "read_file", {"file_path": "/x"})),
            LLMResponse(content="ok", stop_reason=StopReason.STOP),
        ]
    )
    agent = Agent(
        llm=llm,
        tools=ToolExecutor([read_tool]),
        progress=NullProgressSink(),
        rules=[_BlockAllRule()],
    )

    answer = await agent.run("test", context=ctx)

    # The only call is blocked, but the run continues (no halt) and ends when
    # the model itself stops.
    assert answer == "ok"
    assert read_tool.invocations == 0
    tool_msgs = [m for m in ctx.detached.snapshot() if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["c1"]
    assert tool_msgs[0].content == "[test] blocked"


@pytest.mark.asyncio
async def test_multiple_rules_blocking_same_call_join_feedback():
    write_tool = _NoopTool("write_file")
    ctx = MessageListContext()
    llm = _ScriptedLLM(
        [
            _tool_calls_response(("c1", "write_file", {"file_path": "/x"})),
            LLMResponse(content="ok", stop_reason=StopReason.STOP),
        ]
    )
    agent = Agent(
        llm=llm,
        tools=ToolExecutor([write_tool]),
        progress=NullProgressSink(),
        rules=[
            _BlockToolRule("write_file", "[rule-a] first"),
            _BlockToolRule("write_file", "[rule-b] second"),
        ],
    )

    await agent.run("test", context=ctx)

    tool_msgs = [m for m in ctx.detached.snapshot() if m.role == "tool"]
    assert tool_msgs[0].content == "[rule-a] first\n[rule-b] second"
    assert write_tool.invocations == 0
