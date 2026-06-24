from __future__ import annotations

from collections.abc import Sequence

from ouro.core.llm import LLMMessage, LLMResponse, StopReason, ToolCall, ToolOutput
from ouro.core.loop import Agent, NullProgressSink
from ouro.core.tracing import InMemoryTraceExporter, TraceEventType, Tracer


class _ToolRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get_tool_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Echo input",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    def is_tool_readonly(self, name: str) -> bool:
        return True

    def conflict_keys(self, name: str, arguments: dict) -> set[str]:
        return set()

    async def execute_tool_call(self, name: str, arguments: dict) -> ToolOutput:
        self.calls.append((name, arguments))
        return ToolOutput(content="tool output", metadata={"source": "test"})


class _BootstrapHook:
    async def on_run_start(self, ctx, messages):  # type: ignore[no-untyped-def]
        messages.append(LLMMessage(role="user", content=ctx.task))


class _LLM:
    model = "test/model"
    provider_name = "test"

    def __init__(self, responses: Sequence[LLMResponse]) -> None:
        self._responses = list(responses)

    async def call_async(self, **kwargs) -> LLMResponse:  # type: ignore[no-untyped-def]
        return self._responses.pop(0)

    def extract_text(self, response: LLMResponse) -> str:
        return response.content or ""

    def extract_tool_calls(self, response: LLMResponse) -> list[ToolCall]:
        return [
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments={"text": "hello"},
            )
            for tc in response.tool_calls or []
        ]

    def extract_thinking(self, response: LLMResponse) -> str | None:
        return None


async def test_agent_traces_run_and_llm_spans() -> None:
    exporter = InMemoryTraceExporter()
    tracer = Tracer(exporter=exporter, run_id="run-agent")
    llm = _LLM(
        [
            LLMResponse(
                content="done",
                stop_reason=StopReason.STOP,
                usage={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            )
        ]
    )
    agent = Agent(
        llm=llm,
        tools=_ToolRegistry(),
        hooks=(_BootstrapHook(),),
        progress=NullProgressSink(),
        tracer=tracer,
    )

    result = await agent.run("say done")

    assert result == "done"
    completed = {(event.event_type, event.name, event.status): event for event in exporter.events}
    run = completed[(TraceEventType.RUN, "agent.run", "completed")]
    llm_event = completed[(TraceEventType.LLM_CALL, "llm.call", "completed")]
    assert llm_event.parent_span_id == run.span_id
    assert llm_event.attributes["llm.model"] == "test/model"
    assert llm_event.attributes["llm.total_tokens"] == 5
    assert run.attributes["run.task"] == "say done"
    assert run.attributes["run.final_answer"] == "done"
    assert llm_event.attributes["llm.messages"][-1]["content"] == "say done"
    assert llm_event.attributes["llm.tool_schemas"][0]["function"]["name"] == "echo"
    assert llm_event.attributes["llm.response.content"] == "done"
    assert run.attributes["result.length"] == 4


async def test_agent_traces_tool_call_spans() -> None:
    exporter = InMemoryTraceExporter()
    tracer = Tracer(exporter=exporter, run_id="run-tool")
    llm = _LLM(
        [
            LLMResponse(
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "echo", "arguments": "{}"},
                    }
                ],
                stop_reason=StopReason.TOOL_CALLS,
                usage={},
            ),
            LLMResponse(content="done", stop_reason=StopReason.STOP, usage={}),
        ]
    )
    agent = Agent(
        llm=llm,
        tools=_ToolRegistry(),
        hooks=(_BootstrapHook(),),
        progress=NullProgressSink(),
        tracer=tracer,
    )

    result = await agent.run("use tool")

    assert result == "done"
    tool_events = [
        event
        for event in exporter.events
        if event.event_type == TraceEventType.TOOL_CALL and event.name == "echo"
    ]
    assert [event.status for event in tool_events] == ["started", "completed"]
    completed = tool_events[-1]
    assert completed.attributes["tool.name"] == "echo"
    assert completed.attributes["tool.argument_keys"] == ["text"]
    assert completed.attributes["tool.arguments"] == {"text": "hello"}
    assert completed.attributes["tool.result"] == "tool output"
    assert completed.attributes["tool.metadata"] == {"source": "test"}
    assert completed.attributes["tool.result_length"] == len("tool output")
    assert completed.attributes["tool.metadata_keys"] == ["source"]
