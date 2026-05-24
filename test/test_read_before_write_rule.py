"""Tests for ReadBeforeWriteRule (ouro.capabilities.rules.read_before_write).

Unit tests drive the rule's two hooks directly (the rule only uses ctx by
identity, so a plain sentinel object stands in for the loop's RunStatistic).
An integration test runs it through the real Agent loop, and builder tests
confirm it ships on by default.
"""

from __future__ import annotations

import pytest

from ouro.capabilities.builder import AgentBuilder
from ouro.capabilities.rules import ReadBeforeWriteRule
from ouro.capabilities.tools.base import BaseTool
from ouro.capabilities.tools.executor import ToolExecutor
from ouro.core.llm import LLMResponse, StopReason, ToolCall, ToolResult
from ouro.core.loop import Agent, NullProgressSink


def _tc(name: str, file_path: str, cid: str = "c1") -> ToolCall:
    return ToolCall(id=cid, name=name, arguments={"file_path": file_path})


def _tr(name: str, cid: str = "c1", content: str = "ok") -> ToolResult:
    return ToolResult(tool_call_id=cid, content=content, name=name)


# ---------------------------------------------------------------------------
# before_toolcall (block decision)
# ---------------------------------------------------------------------------


def test_blocks_write_to_existing_unread_file(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x")
    rule = ReadBeforeWriteRule()
    msg = rule.before_toolcall(object(), _tc("write_file", str(f)))
    assert msg is not None
    assert "read_file" in msg


def test_blocks_smart_edit_to_existing_unread_file(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x")
    rule = ReadBeforeWriteRule()
    assert rule.before_toolcall(object(), _tc("smart_edit", str(f))) is not None


def test_allows_write_to_nonexistent_file(tmp_path):
    f = tmp_path / "new.py"  # does not exist → creating a new file
    rule = ReadBeforeWriteRule()
    assert rule.before_toolcall(object(), _tc("write_file", str(f))) is None


def test_allows_non_write_tools(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x")
    rule = ReadBeforeWriteRule()
    assert rule.before_toolcall(object(), _tc("read_file", str(f))) is None
    other = ToolCall(id="c", name="shell", arguments={"command": "rm -rf /"})
    assert rule.before_toolcall(object(), other) is None


def test_after_toolcall_never_rewrites_result(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x")
    rule = ReadBeforeWriteRule()
    assert rule.after_toolcall(object(), _tc("read_file", str(f)), _tr("read_file")) is None


# ---------------------------------------------------------------------------
# read/write recording via after_toolcall
# ---------------------------------------------------------------------------


def test_allows_write_after_read(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x")
    rule = ReadBeforeWriteRule()
    ctx = object()
    rule.after_toolcall(ctx, _tc("read_file", str(f)), _tr("read_file"))
    assert rule.before_toolcall(ctx, _tc("write_file", str(f))) is None


def test_allows_edit_after_prior_write(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x")
    rule = ReadBeforeWriteRule()
    ctx = object()
    # Writing a file means the agent now knows its contents → later edit is fine.
    rule.after_toolcall(ctx, _tc("write_file", str(f)), _tr("write_file"))
    assert rule.before_toolcall(ctx, _tc("smart_edit", str(f))) is None


def test_path_is_normalized(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x")
    rule = ReadBeforeWriteRule()
    ctx = object()
    # Read via a non-normalized path; write via the clean path — same file.
    rule.after_toolcall(ctx, _tc("read_file", str(tmp_path / "." / "a.py")), _tr("read_file"))
    assert rule.before_toolcall(ctx, _tc("write_file", str(f))) is None


def test_seen_resets_across_runs(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x")
    rule = ReadBeforeWriteRule()
    run1 = object()
    rule.after_toolcall(run1, _tc("read_file", str(f)), _tr("read_file"))
    assert rule.before_toolcall(run1, _tc("write_file", str(f))) is None
    # A fresh run context clears the seen set; the stale read no longer counts.
    run2 = object()
    assert rule.before_toolcall(run2, _tc("write_file", str(f))) is not None


# ---------------------------------------------------------------------------
# Integration through the Agent loop
# ---------------------------------------------------------------------------


class _StubTool(BaseTool):
    def __init__(self, name: str, readonly: bool = False) -> None:
        self._name = name
        self.readonly = readonly
        self.invocations = 0

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
        return f"{self._name}-ok"


class _ScriptedLLM:
    model = "stub-model"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)

    async def call_async(self, **kwargs) -> LLMResponse:
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="done", stop_reason=StopReason.STOP)

    def extract_text(self, response: LLMResponse) -> str:
        return response.content or ""

    def extract_tool_calls(self, response: LLMResponse) -> list[ToolCall]:
        return list(response.tool_calls or [])


def _call(cid: str, name: str, file_path: str) -> LLMResponse:
    return LLMResponse(
        content=None,
        stop_reason=StopReason.TOOL_CALLS,
        tool_calls=[ToolCall(id=cid, name=name, arguments={"file_path": file_path})],
    )


@pytest.mark.asyncio
async def test_loop_blocks_then_allows_after_read(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("orig")
    read_tool = _StubTool("read_file", readonly=True)
    write_tool = _StubTool("write_file")
    llm = _ScriptedLLM(
        [
            _call("c1", "write_file", str(f)),  # blocked: existing + unread
            _call("c2", "read_file", str(f)),  # dispatched, records the path
            _call("c3", "write_file", str(f)),  # now allowed
            LLMResponse(content="ok", stop_reason=StopReason.STOP),
        ]
    )
    agent = Agent(
        llm=llm,
        tools=ToolExecutor([read_tool, write_tool]),
        progress=NullProgressSink(),
        rules=[ReadBeforeWriteRule()],
    )

    answer = await agent.run("test")

    assert answer == "ok"
    assert read_tool.invocations == 1
    assert write_tool.invocations == 1  # first write blocked, second ran


# ---------------------------------------------------------------------------
# AgentBuilder wiring
# ---------------------------------------------------------------------------


def _rule_names(agent) -> list[str]:
    return [getattr(r, "name", None) for r in agent._core.rules]


def test_builder_adds_read_before_write_by_default():
    agent = AgentBuilder(llm=object()).without_memory().build()
    assert "read_before_write" in _rule_names(agent)


def test_builder_can_disable_read_before_write():
    agent = AgentBuilder(llm=object()).without_memory().without_read_before_write().build()
    assert "read_before_write" not in _rule_names(agent)
