"""Tests for parallel readonly tool execution in core.loop.Agent."""

from __future__ import annotations

import asyncio

import pytest

from ouro.capabilities.tools.base import BaseTool
from ouro.capabilities.tools.executor import ToolExecutor
from ouro.core.llm import ToolCall, ToolResult
from ouro.core.loop import Agent, NullProgressSink
from ouro.core.loop.agent import _RunContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class ReadonlyStubTool(BaseTool):
    """A readonly stub tool for testing."""

    readonly = True

    def __init__(self, tool_name: str, result: str = "ok", delay: float = 0):
        self._name = tool_name
        self._result = result
        self._delay = delay

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
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._result


class WritableStubTool(BaseTool):
    """A writable (non-readonly) stub tool for testing."""

    def __init__(self, tool_name: str, result: str = "ok"):
        self._name = tool_name
        self._result = result

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
        return self._result


class FailingStubTool(BaseTool):
    """A readonly stub tool that raises an exception."""

    readonly = True

    def __init__(self, tool_name: str):
        self._name = tool_name

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
        raise RuntimeError("tool failed")


def _make_tool_call(name: str, call_id: str = "") -> ToolCall:
    if not call_id:
        call_id = f"call_{name}"
    return ToolCall(id=call_id, name=name, arguments={})


def _make_agent_with_tools(tools) -> Agent:
    """Build a core.loop.Agent backed by a ToolExecutor over the given tools."""
    return Agent(
        llm=type("StubLLM", (), {})(),
        tools=ToolExecutor(tools),
        hooks=(),
        progress=NullProgressSink(),
    )


def _make_ctx() -> _RunContext:
    return _RunContext(task="test", progress=NullProgressSink())


# ---------------------------------------------------------------------------
# BaseTool.readonly default
# ---------------------------------------------------------------------------


def test_base_tool_readonly_defaults_to_false():
    tool = WritableStubTool("test")
    assert tool.readonly is False


def test_readonly_tool_has_readonly_true():
    tool = ReadonlyStubTool("test")
    assert tool.readonly is True


# ---------------------------------------------------------------------------
# ToolExecutor.is_tool_readonly
# ---------------------------------------------------------------------------


def test_is_tool_readonly_returns_true():
    executor = ToolExecutor([ReadonlyStubTool("read_file")])
    assert executor.is_tool_readonly("read_file") is True


def test_is_tool_readonly_returns_false():
    executor = ToolExecutor([WritableStubTool("write_file")])
    assert executor.is_tool_readonly("write_file") is False


def test_is_tool_readonly_unknown_tool():
    executor = ToolExecutor([])
    assert executor.is_tool_readonly("nonexistent") is False


# ---------------------------------------------------------------------------
# Parallel vs sequential dispatch decision
# ---------------------------------------------------------------------------


def test_dispatch_picks_parallel_when_all_readonly_and_multi():
    executor = ToolExecutor(
        [ReadonlyStubTool("a"), ReadonlyStubTool("b")]
    )
    tcs = [_make_tool_call("a"), _make_tool_call("b")]
    all_readonly = len(tcs) > 1 and all(executor.is_tool_readonly(tc.name) for tc in tcs)
    assert all_readonly is True


def test_dispatch_picks_sequential_when_mixed():
    executor = ToolExecutor(
        [ReadonlyStubTool("a"), WritableStubTool("b")]
    )
    tcs = [_make_tool_call("a"), _make_tool_call("b")]
    all_readonly = len(tcs) > 1 and all(executor.is_tool_readonly(tc.name) for tc in tcs)
    assert all_readonly is False


def test_dispatch_picks_sequential_for_single_tool():
    executor = ToolExecutor([ReadonlyStubTool("a")])
    tcs = [_make_tool_call("a")]
    all_readonly = len(tcs) > 1 and all(executor.is_tool_readonly(tc.name) for tc in tcs)
    assert all_readonly is False


# ---------------------------------------------------------------------------
# _exec_parallel: correctness, ordering, parallelism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_execution_returns_correct_order():
    """Results should be in the same order as tool_calls, not completion order."""
    agent = _make_agent_with_tools(
        [
            ReadonlyStubTool("slow", result="slow_result", delay=0.05),
            ReadonlyStubTool("fast", result="fast_result", delay=0.01),
        ]
    )
    tcs = [_make_tool_call("slow", "call_1"), _make_tool_call("fast", "call_2")]
    results = await agent._exec_parallel(_make_ctx(), tcs)

    assert len(results) == 2
    assert results[0].content == "slow_result"
    assert results[0].tool_call_id == "call_1"
    assert results[1].content == "fast_result"
    assert results[1].tool_call_id == "call_2"


@pytest.mark.asyncio
async def test_parallel_execution_faster_than_sequential():
    """Parallel execution should be faster than sequential for independent tools."""
    delay = 0.05
    agent = _make_agent_with_tools(
        [
            ReadonlyStubTool("a", result="a", delay=delay),
            ReadonlyStubTool("b", result="b", delay=delay),
            ReadonlyStubTool("c", result="c", delay=delay),
        ]
    )
    tcs = [_make_tool_call("a", "1"), _make_tool_call("b", "2"), _make_tool_call("c", "3")]

    start = asyncio.get_event_loop().time()
    await agent._exec_parallel(_make_ctx(), tcs)
    elapsed = asyncio.get_event_loop().time() - start

    # Sequential would take ~0.15s; parallel should be ~0.05s
    assert elapsed < delay * 2


# ---------------------------------------------------------------------------
# _exec_parallel: error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_one_tool_fails():
    """ToolExecutor catches exceptions and returns error strings."""
    agent = _make_agent_with_tools(
        [ReadonlyStubTool("good", result="ok"), FailingStubTool("bad")]
    )
    tcs = [_make_tool_call("good", "1"), _make_tool_call("bad", "2")]

    results = await agent._exec_parallel(_make_ctx(), tcs)
    assert len(results) == 2
    assert results[0].content == "ok"
    assert "Error" in results[1].content or "tool failed" in results[1].content


# ---------------------------------------------------------------------------
# _exec_sequential: basic check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sequential_execution_works():
    agent = _make_agent_with_tools([WritableStubTool("write", result="written")])
    tcs = [_make_tool_call("write", "call_1")]
    results = await agent._exec_sequential(_make_ctx(), tcs)

    assert len(results) == 1
    assert results[0].content == "written"
    assert results[0].tool_call_id == "call_1"


# ---------------------------------------------------------------------------
# Real tool classes: readonly flag
# ---------------------------------------------------------------------------


def test_real_tools_readonly_flags():
    """Verify readonly flags on actual tool classes."""
    from ouro.capabilities.tools.builtins.advanced_file_ops import GlobTool, GrepTool
    from ouro.capabilities.tools.builtins.file_ops import FileReadTool, FileWriteTool
    from ouro.capabilities.tools.builtins.web_search import WebSearchTool

    assert FileReadTool.readonly is True
    assert GlobTool.readonly is True
    assert GrepTool.readonly is True
    assert WebSearchTool.readonly is True
    assert FileWriteTool.readonly is False
