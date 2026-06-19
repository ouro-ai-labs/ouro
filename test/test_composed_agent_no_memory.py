"""Regression tests for no-memory ComposedAgent runs."""

from __future__ import annotations

from dataclasses import dataclass, field

from ouro.capabilities.builder import AgentBuilder
from ouro.core.llm import LLMMessage, LLMResponse, StopReason


@dataclass
class RecordingLLM:
    seen_messages: list[list[LLMMessage]] = field(default_factory=list)

    async def call_async(self, messages, tools=None, max_tokens=None, **kwargs):
        self.seen_messages.append(list(messages))
        return LLMResponse(content="done", stop_reason=StopReason.STOP)

    def extract_text(self, response: LLMResponse) -> str:
        return response.content or ""

    def extract_tool_calls(self, response: LLMResponse):
        return []

    def to_message(self, response: LLMResponse) -> LLMMessage:
        return LLMMessage(role="assistant", content=response.content)

    @property
    def supports_tools(self) -> bool:
        return True


async def test_no_memory_run_still_includes_user_message() -> None:
    llm = RecordingLLM()
    agent = AgentBuilder().with_llm(llm).without_memory().build()

    result = await agent.run("hello from worker")

    assert result == "done"
    assert llm.seen_messages
    first_call = llm.seen_messages[0]
    assert any(msg.role == "user" and msg.content == "hello from worker" for msg in first_call)
