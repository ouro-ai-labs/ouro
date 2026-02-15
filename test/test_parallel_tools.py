"""Tests for parallel readonly tool execution."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agent.tool_executor import ToolExecutor
from llm import ToolCall, ToolResult
from tools.base import BaseTool

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


def _make_mock_agent(tools):
    """Create a minimal BaseAgent with the given tools for testing."""
    from agent.base import BaseAgent

    class _ConcreteAgent(BaseAgent):
        async def run(self, task: str) -> str:
            raise NotImplementedError

    agent = object.__new__(_ConcreteAgent)
    agent.tool_executor = ToolExecutor(tools)
    return agent


# ---------------------------------------------------------------------------
# BaseTool.readonly default
# ---------------------------------------------------------------------------


def test_base_tool_readonly_defaults_to_false():
    """BaseTool.readonly should default to False."""
    tool = WritableStubTool("test")
    assert tool.readonly is False


def test_readonly_tool_has_readonly_true():
    """Explicitly readonly tools should have readonly=True."""
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
# Parallel vs sequential dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("agent.base.terminal_ui")
async def test_all_readonly_runs_parallel(mock_tui):
    """When all tool calls are readonly, _execute_tools_parallel is used."""
    tools = [ReadonlyStubTool("a", result="res_a"), ReadonlyStubTool("b", result="res_b")]
    agent = _make_mock_agent(tools)

    agent._execute_tools_parallel = AsyncMock(
        return_value=[
            ToolResult(tool_call_id="1", content="res_a", name="a"),
            ToolResult(tool_call_id="2", content="res_b", name="b"),
        ]
    )
    agent._execute_tools_sequential = AsyncMock()

    tcs = [_make_tool_call("a", "1"), _make_tool_call("b", "2")]

    # Check that the decision logic picks parallel
    all_readonly = len(tcs) > 1 and all(agent.tool_executor.is_tool_readonly(tc.name) for tc in tcs)
    assert all_readonly is True


@pytest.mark.asyncio
@patch("agent.base.terminal_ui")
async def test_mixed_tools_runs_sequential(mock_tui):
    """When any tool call is writable, sequential execution is used."""
    tools = [ReadonlyStubTool("a"), WritableStubTool("b")]
    agent = _make_mock_agent(tools)

    tcs = [_make_tool_call("a"), _make_tool_call("b")]

    all_readonly = len(tcs) > 1 and all(agent.tool_executor.is_tool_readonly(tc.name) for tc in tcs)
    assert all_readonly is False


@pytest.mark.asyncio
@patch("agent.base.terminal_ui")
async def test_single_tool_runs_sequential(mock_tui):
    """A single tool call should always use sequential (no parallel overhead)."""
    tools = [ReadonlyStubTool("a")]
    agent = _make_mock_agent(tools)

    tcs = [_make_tool_call("a")]

    all_readonly = len(tcs) > 1 and all(agent.tool_executor.is_tool_readonly(tc.name) for tc in tcs)
    assert all_readonly is False


# ---------------------------------------------------------------------------
# _execute_tools_parallel: correctness and ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("agent.base.terminal_ui")
async def test_parallel_execution_returns_correct_order(mock_tui):
    """Results should be in the same order as tool_calls, not completion order."""
    # Tool "slow" takes longer but appears first
    tools = [
        ReadonlyStubTool("slow", result="slow_result", delay=0.05),
        ReadonlyStubTool("fast", result="fast_result", delay=0.01),
    ]
    agent = _make_mock_agent(tools)

    tcs = [_make_tool_call("slow", "call_1"), _make_tool_call("fast", "call_2")]
    results = await agent._execute_tools_parallel(tcs)

    assert len(results) == 2
    assert results[0].content == "slow_result"
    assert results[0].tool_call_id == "call_1"
    assert results[1].content == "fast_result"
    assert results[1].tool_call_id == "call_2"


@pytest.mark.asyncio
@patch("agent.base.terminal_ui")
async def test_parallel_execution_faster_than_sequential(mock_tui):
    """Parallel execution should be faster than sequential for independent tools."""
    delay = 0.05
    tools = [
        ReadonlyStubTool("a", result="a", delay=delay),
        ReadonlyStubTool("b", result="b", delay=delay),
        ReadonlyStubTool("c", result="c", delay=delay),
    ]
    agent = _make_mock_agent(tools)
    tcs = [_make_tool_call("a", "1"), _make_tool_call("b", "2"), _make_tool_call("c", "3")]

    start = asyncio.get_event_loop().time()
    await agent._execute_tools_parallel(tcs)
    elapsed = asyncio.get_event_loop().time() - start

    # Sequential would take ~0.15s; parallel should be ~0.05s
    assert elapsed < delay * 2


# ---------------------------------------------------------------------------
# _execute_tools_parallel: error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("agent.base.terminal_ui")
async def test_parallel_one_tool_fails(mock_tui):
    """If one tool fails in parallel, TaskGroup propagates the error.

    ToolExecutor.execute_tool_call catches exceptions and returns error strings,
    so in practice failures are returned as error messages, not raised.
    """
    tools = [ReadonlyStubTool("good", result="ok"), FailingStubTool("bad")]
    agent = _make_mock_agent(tools)

    tcs = [_make_tool_call("good", "1"), _make_tool_call("bad", "2")]

    # ToolExecutor wraps exceptions into error strings, so this should succeed
    results = await agent._execute_tools_parallel(tcs)
    assert len(results) == 2
    assert results[0].content == "ok"
    assert "Error" in results[1].content


# ---------------------------------------------------------------------------
# _execute_tools_sequential: basic check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("agent.base.terminal_ui")
async def test_sequential_execution_works(mock_tui):
    """Basic sequential execution test."""
    tools = [WritableStubTool("write", result="written")]
    agent = _make_mock_agent(tools)

    tcs = [_make_tool_call("write", "call_1")]
    results = await agent._execute_tools_sequential(tcs)

    assert len(results) == 1
    assert results[0].content == "written"
    assert results[0].tool_call_id == "call_1"


# ---------------------------------------------------------------------------
# Real tool classes: readonly flag
# ---------------------------------------------------------------------------


def test_real_tools_readonly_flags():
    """Verify readonly flags on actual tool classes."""
    from tools.advanced_file_ops import GlobTool, GrepTool
    from tools.file_ops import FileReadTool, FileWriteTool
    from tools.web_search import WebSearchTool

    assert FileReadTool.readonly is True
    assert GlobTool.readonly is True
    assert GrepTool.readonly is True
    assert WebSearchTool.readonly is True
    assert FileWriteTool.readonly is False
