"""Regression tests for usage_callback wiring in the core loop.

Locks in the fix for the bug where ``TokenTracker.record_usage`` was
never called after the Hook protocol was slimmed in #175, leaving the
TUI status bar permanently at ``Total: 0↓ 0↑``.
"""

from __future__ import annotations

import pytest

from ouro.capabilities.tools.executor import ToolExecutor
from ouro.core.llm import LLMResponse, StopReason
from ouro.core.loop import Agent, NullProgressSink


class _StubLLM:
    """Minimal LLM stub returning a single STOP response with usage."""

    model = "stub-model"

    def __init__(self) -> None:
        self.calls: int = 0

    async def call_async(self, **kwargs) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            content="hi",
            stop_reason=StopReason.STOP,
            usage={"input_tokens": 11, "output_tokens": 7},
        )

    def extract_text(self, response: LLMResponse) -> str:
        return response.content or ""

    def extract_tool_calls(self, response: LLMResponse) -> list:
        return []


@pytest.mark.asyncio
async def test_agent_invokes_usage_callback_on_llm_response():
    received: list[dict[str, int]] = []
    agent = Agent(
        llm=_StubLLM(),
        tools=ToolExecutor([]),
        hooks=(),
        progress=NullProgressSink(),
        usage_callback=lambda usage: received.append(dict(usage)),
    )
    await agent.run("hello")
    assert received == [{"input_tokens": 11, "output_tokens": 7}]


@pytest.mark.asyncio
async def test_agent_builder_wires_usage_into_memory_token_tracker(tmp_path):
    from ouro.capabilities.builder import AgentBuilder

    builder = (
        AgentBuilder()
        .with_llm(_StubLLM())  # type: ignore[arg-type]
        .with_memory(
            sessions_dir=str(tmp_path / "sessions"),
            memory_dir=str(tmp_path / "memory"),
        )
    )
    composed = builder.build()
    assert composed.memory is not None

    await composed.run("hi")

    stats = composed.get_memory_stats()
    assert stats["total_input_tokens"] == 11
    assert stats["total_output_tokens"] == 7
