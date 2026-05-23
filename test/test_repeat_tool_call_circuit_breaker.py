"""Regression tests for the repeated-tool-call circuit breaker in Agent.

Locks in the fix for the death loop where compaction summaries describe
prior repetitive tool calls as "patterns", causing the model to resume
emitting the identical call iteration after iteration.
"""

from __future__ import annotations

import pytest

from ouro.capabilities.tools.base import BaseTool
from ouro.capabilities.tools.executor import ToolExecutor
from ouro.core.llm import LLMResponse, StopReason, ToolCall
from ouro.core.loop import Agent, NullProgressSink
from ouro.core.loop.rules import _tool_call_iter_signature


class _NoopTool(BaseTool):
    readonly = True

    def __init__(self, name: str = "read_file") -> None:
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
        return "stub-result"


class _ScriptedLLM:
    """LLM stub that emits a fixed list of responses, then a STOP."""

    model = "stub-model"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: int = 0

    async def call_async(self, **kwargs) -> LLMResponse:
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="done", stop_reason=StopReason.STOP)

    def extract_text(self, response: LLMResponse) -> str:
        return response.content or ""

    def extract_tool_calls(self, response: LLMResponse) -> list[ToolCall]:
        return list(response.tool_calls or [])


def _tool_call_response(call_id: str, name: str, args: dict) -> LLMResponse:
    return LLMResponse(
        content=None,
        stop_reason=StopReason.TOOL_CALLS,
        tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
    )


# ---------------------------------------------------------------------------
# _tool_call_iter_signature
# ---------------------------------------------------------------------------


def test_signature_normalizes_argument_key_order():
    a = ToolCall(id="1", name="read_file", arguments={"file_path": "/x", "offset": 0})
    b = ToolCall(id="2", name="read_file", arguments={"offset": 0, "file_path": "/x"})
    assert _tool_call_iter_signature([a]) == _tool_call_iter_signature([b])


def test_signature_differs_when_arguments_differ():
    a = ToolCall(id="1", name="read_file", arguments={"file_path": "/x"})
    b = ToolCall(id="2", name="read_file", arguments={"file_path": "/y"})
    assert _tool_call_iter_signature([a]) != _tool_call_iter_signature([b])


def test_signature_handles_non_json_safe_arguments():
    # Should not raise on exotic values; falls back to string repr.
    class Weird:
        def __repr__(self) -> str:
            return "<weird>"

    tc = ToolCall(id="1", name="x", arguments={"v": Weird()})
    assert _tool_call_iter_signature([tc])  # smoke test: doesn't raise


# ---------------------------------------------------------------------------
# Circuit breaker behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_third_identical_call_is_intercepted_with_synthetic_feedback():
    """At threshold=3, the 3rd identical iteration short-circuits dispatch."""
    args = {"file_path": "/m.py", "offset": 0, "limit": 100}
    tool = _NoopTool("read_file")
    llm = _ScriptedLLM(
        [
            _tool_call_response("c1", "read_file", args),
            _tool_call_response("c2", "read_file", args),
            _tool_call_response("c3", "read_file", args),  # intercepted
            LLMResponse(content="ok", stop_reason=StopReason.STOP),
        ]
    )
    agent = Agent(
        llm=llm,
        tools=ToolExecutor([tool]),
        hooks=(),
        progress=NullProgressSink(),
    )
    answer = await agent.run("test")
    assert answer == "ok"
    # 1st & 2nd dispatched; 3rd intercepted → tool actually ran only twice.
    assert tool.invocations == 2


@pytest.mark.asyncio
async def test_sustained_repeats_keep_being_intercepted_without_halting():
    """The breaker warns every repeat past threshold but never stops the loop."""
    args = {"file_path": "/m.py", "offset": 0, "limit": 100}
    tool = _NoopTool("read_file")
    # 5 identical repeats, then the model finally relents and stops.
    llm = _ScriptedLLM(
        [_tool_call_response(f"c{i}", "read_file", args) for i in range(1, 6)]
        + [LLMResponse(content="ok", stop_reason=StopReason.STOP)]
    )
    agent = Agent(
        llm=llm,
        tools=ToolExecutor([tool]),
        hooks=(),
        progress=NullProgressSink(),
    )
    answer = await agent.run("test")
    # Run is not halted by the rule — it ends when the model itself stops.
    assert answer == "ok"
    # 1st & 2nd dispatched; 3rd..5th intercepted (replaced, not dispatched).
    assert tool.invocations == 2
    # Every repeat still triggered an LLM turn; the rule never short-circuits.
    assert llm.calls == 6


@pytest.mark.asyncio
async def test_changing_arguments_resets_repeat_counter():
    """Same tool name but different args is NOT a repeat."""
    tool = _NoopTool("read_file")
    llm = _ScriptedLLM(
        [
            _tool_call_response("c1", "read_file", {"file_path": "/a.py"}),
            _tool_call_response("c2", "read_file", {"file_path": "/a.py"}),
            _tool_call_response("c3", "read_file", {"file_path": "/b.py"}),
            _tool_call_response("c4", "read_file", {"file_path": "/b.py"}),
            LLMResponse(content="ok", stop_reason=StopReason.STOP),
        ]
    )
    agent = Agent(
        llm=llm,
        tools=ToolExecutor([tool]),
        hooks=(),
        progress=NullProgressSink(),
    )
    answer = await agent.run("test")
    assert answer == "ok"
    # No interception — all 4 calls dispatched.
    assert tool.invocations == 4


@pytest.mark.asyncio
async def test_circuit_breaker_disabled_by_zero_threshold():
    """Setting threshold=0 disables the safety net (back to old behavior)."""
    args = {"file_path": "/m.py"}
    tool = _NoopTool("read_file")
    llm = _ScriptedLLM(
        [_tool_call_response(f"c{i}", "read_file", args) for i in range(1, 4)]
        + [LLMResponse(content="ok", stop_reason=StopReason.STOP)]
    )
    agent = Agent(
        llm=llm,
        tools=ToolExecutor([tool]),
        hooks=(),
        progress=NullProgressSink(),
        repeat_tool_call_threshold=0,
    )
    answer = await agent.run("test")
    assert answer == "ok"
    # All 3 dispatched (no interception).
    assert tool.invocations == 3
