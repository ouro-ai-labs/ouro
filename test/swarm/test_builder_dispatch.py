"""Builder-level tests for dispatcher-backed agent-team execution."""

from __future__ import annotations

from ouro.capabilities.builder import AgentBuilder


class FakeLLM:
    async def call_async(self, **kwargs):
        from ouro.core.llm import LLMResponse, StopReason

        return LLMResponse(content="single-agent-done", stop_reason=StopReason.STOP)

    def extract_text(self, response):
        return response.content

    def extract_tool_calls(self, response):
        return []

    def to_message(self, response):
        from ouro.core.llm import LLMMessage

        return LLMMessage(role="assistant", content=response.content)

    @property
    def supports_tools(self) -> bool:
        return True


class StubDispatcher:
    def __init__(self, single_agent_runner):
        self.single_agent_runner = single_agent_runner
        self.calls: list[str] = []

    async def run(self, task: str) -> str:
        self.calls.append(task)
        return f"dispatched: {task}"


async def test_agent_team_run_uses_dispatcher_factory() -> None:
    holder: dict[str, StubDispatcher] = {}

    def dispatcher_factory(single_agent_runner):
        dispatcher = StubDispatcher(single_agent_runner)
        holder["dispatcher"] = dispatcher
        return dispatcher

    agent = (
        AgentBuilder()
        .with_llm(FakeLLM())
        .with_agent_team(enabled=True)
        .without_memory()
        .with_dispatcher_factory(dispatcher_factory)
        .build()
    )

    result = await agent.run("complex task")

    assert result == "dispatched: complex task"
    assert holder["dispatcher"].calls == ["complex task"]


async def test_non_team_run_keeps_single_agent_path() -> None:
    agent = AgentBuilder().with_llm(FakeLLM()).without_memory().build()

    result = await agent.run("simple task")

    assert result == "single-agent-done"
