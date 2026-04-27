from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ouro.core.llm import LLMMessage, LLMResponse, StopReason
from ouro.core.llm.reasoning import REASONING_EFFORT_CHOICES, normalize_reasoning_effort
from ouro.core.loop import Agent, NullProgressSink


def test_normalize_reasoning_effort_basics():
    assert normalize_reasoning_effort(None) is None
    assert normalize_reasoning_effort("") is None
    assert normalize_reasoning_effort("default") is None
    assert normalize_reasoning_effort("off") == "none"
    assert normalize_reasoning_effort("NONE") == "none"
    assert normalize_reasoning_effort("high") == "high"

    with pytest.raises(ValueError):
        normalize_reasoning_effort("bogus")

    # Sanity: our choices list is what CLI/interactive advertises.
    assert "off" in REASONING_EFFORT_CHOICES
    assert "none" in REASONING_EFFORT_CHOICES


def test_reasoning_menu_levels_stay_in_sync():
    # The menu should expose the same user-facing options we document.
    from ouro.interfaces.tui import reasoning_ui

    menu_values = [v for v, _ in reasoning_ui._LEVELS]  # noqa: SLF001
    assert "none" not in menu_values
    assert set(menu_values) >= {
        "default",
        "off",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }


class _StaticToolRegistry:
    """Minimal ToolRegistry for tests — no tools."""

    def get_tool_schemas(self):
        return []

    def is_tool_readonly(self, name: str) -> bool:
        return True

    async def execute_tool_call(self, name: str, arguments):
        raise NotImplementedError


def _make_llm() -> object:
    """Build a stub LLM that returns a STOP response and records call kwargs."""
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
        hooks=(),
        progress=NullProgressSink(),
    )
    await agent.run("hello", initial_messages=[LLMMessage(role="user", content="hello")])

    _, kwargs = llm.call_async.call_args
    assert "reasoning_effort" not in kwargs


@pytest.mark.asyncio
async def test_core_agent_injects_reasoning_effort_when_set():
    llm = _make_llm()
    agent = Agent(
        llm=llm,
        tools=_StaticToolRegistry(),
        hooks=(),
        progress=NullProgressSink(),
    )
    agent.set_reasoning_effort("high")
    await agent.run("hi", initial_messages=[LLMMessage(role="user", content="hi")])

    _, kwargs = llm.call_async.call_args
    assert kwargs["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_interactive_reasoning_command_sets_agent(monkeypatch):
    from ouro.core.llm.reasoning import display_reasoning_effort, normalize_reasoning_effort
    from ouro.interfaces.tui import interactive

    InteractiveSession = interactive.InteractiveSession

    class _FakeAgent:
        def __init__(self):
            self._reasoning_effort = None
            self.model_manager = type(
                "MM",
                (),
                {"config_path": "/tmp/models.yaml", "get_current_model": lambda self: None},
            )()
            self.memory = type("Mem", (), {"get_stats": lambda self: {}})()

        def set_reasoning_effort(self, value):
            self._reasoning_effort = normalize_reasoning_effort(value)

        def get_reasoning_effort(self):
            return display_reasoning_effort(self._reasoning_effort)

        def switch_model(self, model_id: str) -> bool:  # noqa: ARG002
            return True

        def get_current_model_info(self):
            return None

    monkeypatch.setattr(InteractiveSession, "_setup_signal_handler", lambda self: None)

    infos: list[str] = []
    successes: list[str] = []
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(interactive.terminal_ui, "print_info", lambda msg: infos.append(msg))
    monkeypatch.setattr(interactive.terminal_ui, "print_success", lambda msg: successes.append(msg))
    monkeypatch.setattr(
        interactive.terminal_ui,
        "print_error",
        lambda msg, title="Error": errors.append((title, msg)),
    )

    session = InteractiveSession(_FakeAgent())

    # Menu path: /reasoning (no args) opens the picker and sets the value.
    async def _fake_pick_reasoning_effort(**kwargs):  # noqa: ARG002
        return "off"

    monkeypatch.setattr(interactive, "pick_reasoning_effort", _fake_pick_reasoning_effort)
    handled = await session._handle_command("/reasoning")
    assert handled is True
    assert successes and "reasoning_effort set" in successes[-1]

    # Args are rejected to keep UX consistent.
    handled = await session._handle_command("/reasoning off")
    assert handled is True
    assert errors and errors[-1][0] == "Error"
