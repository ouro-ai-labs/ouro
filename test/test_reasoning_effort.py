from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agent.base import BaseAgent
from llm import LLMMessage, LLMResponse, StopReason
from llm.reasoning import REASONING_EFFORT_CHOICES, normalize_reasoning_effort


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
    from utils.tui import reasoning_ui

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


@pytest.mark.asyncio
async def test_agent_call_llm_injects_reasoning_effort(monkeypatch):
    class _ConcreteAgent(BaseAgent):
        async def run(self, task: str) -> str:  # noqa: ARG002
            raise NotImplementedError

    # No-op spinner to keep the test deterministic.
    class _NoopSpinner:
        def __init__(self, *args, **kwargs):  # noqa: D401, ARG002
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

    monkeypatch.setattr("agent.base.AsyncSpinner", _NoopSpinner)

    # Bypass BaseAgent.__init__ to avoid pulling in MemoryManager/Compressor.
    agent = object.__new__(_ConcreteAgent)
    agent.llm = type("LLM", (), {})()
    agent.llm.call_async = AsyncMock(
        return_value=LLMResponse(content="ok", stop_reason=StopReason.STOP)
    )

    # Default: do not inject.
    await agent._call_llm(messages=[LLMMessage(role="user", content="hi")], tools=None)
    _, kwargs = agent.llm.call_async.call_args
    assert "reasoning_effort" not in kwargs

    # Set run-scoped value: inject unless explicitly overridden per-call.
    agent.set_reasoning_effort("high")
    await agent._call_llm(messages=[LLMMessage(role="user", content="hi")], tools=None)
    _, kwargs = agent.llm.call_async.call_args
    assert kwargs["reasoning_effort"] == "high"

    await agent._call_llm(
        messages=[LLMMessage(role="user", content="hi")],
        tools=None,
        reasoning_effort="low",
    )
    _, kwargs = agent.llm.call_async.call_args
    assert kwargs["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_interactive_reasoning_command_sets_agent(monkeypatch):
    interactive = pytest.importorskip("interactive")
    InteractiveSession = interactive.InteractiveSession
    from llm.reasoning import display_reasoning_effort, normalize_reasoning_effort

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

    # Set value
    handled = await session._handle_command("/reasoning off")
    assert handled is True
    assert successes and "reasoning_effort set" in successes[-1]

    # Invalid value
    handled = await session._handle_command("/reasoning bogus")
    assert handled is True
    assert errors and errors[-1][0] == "Invalid reasoning_effort"
