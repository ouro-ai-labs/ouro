"""Tests for parallel readonly tool execution in core.loop.Agent."""

from __future__ import annotations

import asyncio

import pytest

from ouro.capabilities.tools.base import BaseTool
from ouro.capabilities.tools.executor import ToolExecutor
from ouro.core.llm import ToolCall
from ouro.core.loop import Agent, NullProgressSink, RunStatistic

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


class ScopedWritableStubTool(WritableStubTool):
    """Writable stub that declares its conflict scope from arguments."""

    def conflict_keys(self, **kwargs):
        path = kwargs.get("path")
        if not isinstance(path, str) or not path:
            return None
        return {path}


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


def _make_tool_call(name: str, call_id: str = "", **arguments) -> ToolCall:
    if not call_id:
        call_id = f"call_{name}"
    return ToolCall(id=call_id, name=name, arguments=arguments)


def _make_agent_with_tools(tools) -> Agent:
    """Build a core.loop.Agent backed by a ToolExecutor over the given tools."""
    return Agent(
        llm=type("StubLLM", (), {})(),
        tools=ToolExecutor(tools),
        hooks=(),
        progress=NullProgressSink(),
    )


def _make_ctx() -> RunStatistic:
    return RunStatistic(task="test", progress=NullProgressSink())


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
# BaseTool.conflict_keys defaults + ToolExecutor passthrough
# ---------------------------------------------------------------------------


def test_conflict_keys_default_readonly_is_empty_set():
    assert ReadonlyStubTool("a").conflict_keys() == set()


def test_conflict_keys_default_writable_is_none():
    assert WritableStubTool("a").conflict_keys() is None


def test_executor_conflict_keys_unknown_tool_is_none():
    executor = ToolExecutor([])
    assert executor.conflict_keys("nonexistent", {}) is None


def test_executor_conflict_keys_passes_arguments_through():
    executor = ToolExecutor([ScopedWritableStubTool("write")])
    assert executor.conflict_keys("write", {"path": "/abs/x"}) == {"/abs/x"}
    assert executor.conflict_keys("write", {}) is None


# ---------------------------------------------------------------------------
# Agent._build_batches: prefix-greedy grouping
# ---------------------------------------------------------------------------


def test_build_batches_all_readonly_one_parallel_batch():
    agent = _make_agent_with_tools([ReadonlyStubTool("a"), ReadonlyStubTool("b")])
    tcs = [_make_tool_call("a"), _make_tool_call("b")]
    assert agent._build_batches(tcs) == [[0, 1]]


def test_build_batches_unknown_scope_runs_alone():
    # A non-readonly tool with no conflict_keys override returns None,
    # so it must run alone and split surrounding readonly calls.
    agent = _make_agent_with_tools([ReadonlyStubTool("ro"), WritableStubTool("wr")])
    tcs = [_make_tool_call("ro", "1"), _make_tool_call("wr", "2"), _make_tool_call("ro", "3")]
    assert agent._build_batches(tcs) == [[0], [1], [2]]


def test_build_batches_disjoint_scoped_writes_parallel():
    agent = _make_agent_with_tools([ScopedWritableStubTool("wr")])
    tcs = [
        _make_tool_call("wr", "1", path="/a"),
        _make_tool_call("wr", "2", path="/b"),
    ]
    assert agent._build_batches(tcs) == [[0, 1]]


def test_build_batches_overlapping_scoped_writes_split():
    agent = _make_agent_with_tools([ScopedWritableStubTool("wr")])
    tcs = [
        _make_tool_call("wr", "1", path="/a"),
        _make_tool_call("wr", "2", path="/a"),
    ]
    assert agent._build_batches(tcs) == [[0], [1]]


def test_build_batches_readonly_joins_scoped_write_batch():
    # readonly's empty key set is disjoint with anything; it should join.
    agent = _make_agent_with_tools([ReadonlyStubTool("ro"), ScopedWritableStubTool("wr")])
    tcs = [
        _make_tool_call("ro", "1"),
        _make_tool_call("wr", "2", path="/a"),
        _make_tool_call("ro", "3"),
    ]
    assert agent._build_batches(tcs) == [[0, 1, 2]]


def test_build_batches_single_tool_one_singleton_batch():
    agent = _make_agent_with_tools([ReadonlyStubTool("a")])
    tcs = [_make_tool_call("a")]
    assert agent._build_batches(tcs) == [[0]]


def test_build_batches_preserves_emit_order_across_batches():
    agent = _make_agent_with_tools([ScopedWritableStubTool("wr"), ReadonlyStubTool("ro")])
    tcs = [
        _make_tool_call("wr", "1", path="/a"),
        _make_tool_call("wr", "2", path="/a"),  # conflicts with #1
        _make_tool_call("ro", "3"),  # joins batch 2
    ]
    assert agent._build_batches(tcs) == [[0], [1, 2]]


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
    agent = _make_agent_with_tools([ReadonlyStubTool("good", result="ok"), FailingStubTool("bad")])
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


def test_file_write_tool_conflict_keys_returns_abs_path():
    """FileWriteTool opts in to scoped batching via abspath of file_path."""
    import os

    from ouro.capabilities.tools.builtins.file_ops import FileWriteTool

    tool = FileWriteTool()
    keys = tool.conflict_keys(file_path="relative/path.txt", content="x")
    assert keys == {os.path.abspath("relative/path.txt")}


def test_file_write_tool_conflict_keys_missing_path_is_none():
    """Without a usable file_path argument, fall back to unknown scope."""
    from ouro.capabilities.tools.builtins.file_ops import FileWriteTool

    tool = FileWriteTool()
    assert tool.conflict_keys() is None
    assert tool.conflict_keys(file_path="") is None


def test_smart_edit_tool_conflict_keys_returns_abs_path():
    """SmartEditTool opts in via abspath of file_path (all edit modes)."""
    import os

    from ouro.capabilities.tools.builtins.smart_edit import SmartEditTool

    tool = SmartEditTool()
    keys = tool.conflict_keys(file_path="relative/path.py", mode="diff_replace")
    assert keys == {os.path.abspath("relative/path.py")}


def test_smart_edit_tool_conflict_keys_missing_path_is_none():
    from ouro.capabilities.tools.builtins.smart_edit import SmartEditTool

    tool = SmartEditTool()
    assert tool.conflict_keys() is None
    assert tool.conflict_keys(file_path="") is None


# ---------------------------------------------------------------------------
# _dispatch_tools: end-to-end with mixed readonly + scoped writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_runs_disjoint_writes_in_one_parallel_batch():
    """Two scoped writes to disjoint paths must run concurrently."""
    delay = 0.05

    class DelayedScopedWrite(ScopedWritableStubTool):
        async def execute(self, **kwargs) -> str:
            await asyncio.sleep(delay)
            return self._result

    agent = _make_agent_with_tools([DelayedScopedWrite("wr", result="ok")])
    tcs = [
        _make_tool_call("wr", "1", path="/a"),
        _make_tool_call("wr", "2", path="/b"),
    ]

    start = asyncio.get_event_loop().time()
    results = await agent._dispatch_tools(_make_ctx(), tcs)
    elapsed = asyncio.get_event_loop().time() - start

    assert [r.tool_call_id for r in results] == ["1", "2"]
    assert elapsed < delay * 2  # parallel, not sequential


@pytest.mark.asyncio
async def test_dispatch_preserves_order_across_split_batches():
    agent = _make_agent_with_tools([ScopedWritableStubTool("wr"), ReadonlyStubTool("ro")])
    tcs = [
        _make_tool_call("wr", "1", path="/a"),
        _make_tool_call("wr", "2", path="/a"),  # conflicts → new batch
        _make_tool_call("ro", "3"),  # joins batch 2
    ]
    results = await agent._dispatch_tools(_make_ctx(), tcs)
    assert [r.tool_call_id for r in results] == ["1", "2", "3"]
