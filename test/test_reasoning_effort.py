"""Tests for reasoning effort wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ouro.core.llm import LLMMessage, LLMResponse, StopReason
from ouro.core.loop import Agent, NullProgressSink


class _StaticToolRegistry:
    def get_tool_schemas(self):
        return []

    def is_tool_readonly(self, name: str) -> bool:
        return True

    async def execute_tool_call(self, name: str, arguments: dict):
        return ""


class _BootstrapHook:
    async def on_run_start(self, ctx, messages):
        messages.append(LLMMessage(role="user", content=ctx.task))


def _make_llm():
    llm = type("LLM", (), {})()
    llm.call_async = AsyncMock(
        return_value=LLMResponse(content="ok", stop_reason=StopReason.STOP, usage={})
    )
    llm.extract_text = lambda r: (r.content or "")
    llm.extract_tool_calls = lambda r: []
    llm.format_tool_results = lambda results: []
    return llm


@pytest.mark.asyncio
async def test_core_agent_omits_reasoning_effort_by_default():
    llm = _make_llm()
    agent = Agent(
        llm=llm,
        tools=_StaticToolRegistry(),
        hooks=(_BootstrapHook(),),
        progress=NullProgressSink(),
    )
    await agent.run("hello")

    _, kwargs = llm.call_async.call_args
    assert "reasoning_effort" not in kwargs


@pytest.mark.asyncio
async def test_core_agent_injects_reasoning_effort_when_set():
    llm = _make_llm()
    agent = Agent(
        llm=llm,
        tools=_StaticToolRegistry(),
        hooks=(_BootstrapHook(),),
        progress=NullProgressSink(),
    )
    agent.set_reasoning_effort("high")
    await agent.run("hi")

    _, kwargs = llm.call_async.call_args
    assert kwargs["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_interactive_reasoning_ui_can_be_imported():
    from ouro.interfaces.tui.reasoning_ui import pick_reasoning_effort

    assert callable(pick_reasoning_effort)
