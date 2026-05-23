"""Tests for the pluggable loop Rule abstraction (ouro.core.loop.rules).

Covers the generic seam — per-call blocking, halting, per-run reset, and the
post-dispatch ``observe`` hook — independent of the repeated-tool-call rule
(which keeps its dedicated regression suite in
``test_repeat_tool_call_circuit_breaker.py``).
"""

from __future__ import annotations

import pytest

from ouro.capabilities.tools.base import BaseTool
from ouro.capabilities.tools.executor import ToolExecutor
from ouro.core.llm import LLMResponse, StopReason, ToolCall, ToolResult
from ouro.core.loop import Agent, NullProgressSink
from ouro.core.loop.rules import RuleOutcome, RuleViolation


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
    """Blocks any call to a named tool with fixed feedback; never halts."""

    name = "block-tool"

    def __init__(self, tool_name: str, message: str) -> None:
        self._tool_name = tool_name
        self._message = message
        self.run_starts = 0
        self.observed: list[tuple[str, str]] = []

    def on_run_start(self) -> None:
        self.run_starts += 1

    def check(self, ctx, tool_calls: list[ToolCall]) -> RuleOutcome:
        violations = tuple(
            RuleViolation(tc.id, self._message) for tc in tool_calls if tc.name == self._tool_name
        )
        return RuleOutcome(violations=violations)

    def observe(self, ctx, executed: list[tuple[ToolCall, ToolResult]]) -> None:
        self.observed.extend((tc.name, tr.content) for tc, tr in executed)


@pytest.mark.asyncio
async def test_rule_blocks_one_call_and_dispatches_sibling():
    """A per-call violation blocks just that call; the sibling still runs."""
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
    assert write_tool.invocations == 0  # blocked
    assert read_tool.invocations == 1  # dispatched
    # observe only sees the dispatched call, not the blocked one.
    assert rule.observed == [("read_file", "read_file-result")]


@pytest.mark.asyncio
async def test_blocked_call_feedback_reaches_history_in_order():
    """Blocked call gets a synthetic tool_result; ordering follows tool_calls."""
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
    agent = Agent(
        llm=llm,
        tools=ToolExecutor([read_tool, write_tool]),
        progress=NullProgressSink(),
        rules=[_BlockToolRule("write_file", "[test] blocked")],
    )
    ctx = None  # use default transient context

    from ouro.core.loop import MessageListContext

    ctx = MessageListContext()
    await agent.run("test", context=ctx)

    tool_msgs = [m for m in ctx.detached.snapshot() if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["c1", "c2"]
    assert tool_msgs[0].content == "[test] blocked"
    assert tool_msgs[1].content == "read_file-result"


class _HaltRule:
    name = "halt"

    def on_run_start(self) -> None:
        pass

    def check(self, ctx, tool_calls: list[ToolCall]) -> RuleOutcome:
        return RuleOutcome(
            violations=tuple(RuleViolation(tc.id, "[test] stop") for tc in tool_calls),
            halt=True,
            halt_message="[test] halted by rule",
        )

    def observe(self, ctx, executed) -> None:
        pass


@pytest.mark.asyncio
async def test_halting_rule_returns_halt_message_and_emits_results():
    read_tool = _NoopTool("read_file")
    llm = _ScriptedLLM([_tool_calls_response(("c1", "read_file", {"file_path": "/x"}))])
    from ouro.core.loop import MessageListContext

    ctx = MessageListContext()
    agent = Agent(
        llm=llm,
        tools=ToolExecutor([read_tool]),
        progress=NullProgressSink(),
        rules=[_HaltRule()],
    )

    answer = await agent.run("test", context=ctx)

    assert answer == "[test] halted by rule"
    assert read_tool.invocations == 0  # halted before dispatch
    # The single tool_call still gets a tool_result (API requirement).
    tool_msgs = [m for m in ctx.detached.snapshot() if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["c1"]


@pytest.mark.asyncio
async def test_on_run_start_resets_between_runs():
    """Rule lifecycle reset fires once per Agent.run()."""
    tool = _NoopTool("read_file")
    rule = _BlockToolRule("write_file", "[test] x")

    def _fresh_llm():
        return _ScriptedLLM([LLMResponse(content="ok", stop_reason=StopReason.STOP)])

    agent = Agent(llm=_fresh_llm(), tools=ToolExecutor([tool]), rules=[rule])
    await agent.run("first")
    agent.llm = _fresh_llm()
    await agent.run("second")

    assert rule.run_starts == 2


@pytest.mark.asyncio
async def test_multiple_rules_blocking_same_call_join_feedback():
    write_tool = _NoopTool("write_file")
    from ouro.core.loop import MessageListContext

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
