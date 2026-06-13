from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from ouro.core.llm import ToolCall, ToolOutput
from ouro.core.loop.agent import Agent
from ouro.core.loop.context import RunStatistic
from ouro.core.loop.protocols import ProgressEvent


class _ProgressRecorder:
    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    def emit(self, event: ProgressEvent) -> None:
        self.events.append(event)

    @asynccontextmanager
    async def spinner(self, label: str, title: str | None = None):
        yield None

    def on_session_loaded(self, messages):
        return None


class _ToolRegistryStub:
    def get_tool_schemas(self):
        return []

    def is_tool_readonly(self, name: str) -> bool:
        return False

    def conflict_keys(self, name: str, arguments: dict[str, object]):
        return None

    async def execute_tool_call(self, name: str, arguments: dict[str, object]) -> ToolOutput:
        return ToolOutput(content="tool content", metadata={"source": "stub"})


@pytest.mark.asyncio
async def test_sequential_tool_result_event_uses_tool_content() -> None:
    progress = _ProgressRecorder()
    agent = Agent(llm=object(), tools=_ToolRegistryStub(), progress=progress)

    result = await agent._exec_sequential(
        ctx=RunStatistic(task="demo", progress=progress),
        tool_calls=[ToolCall(id="call-1", name="demo_tool", arguments={"value": 1})],
    )

    assert result[0].content == "tool content"
    assert progress.events == [
        ProgressEvent(
            kind="tool_call",
            payload={"name": "demo_tool", "arguments": {"value": 1}},
        ),
        ProgressEvent(kind="tool_result", payload={"text": "tool content"}),
    ]
