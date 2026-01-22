"""Pytest fixtures for memory module tests."""

import pytest

from config import Config
from llm.base import LLMMessage, LLMResponse


@pytest.fixture
def set_memory_config(monkeypatch):
    """Fixture to temporarily set memory configuration values.

    Usage:
        def test_something(set_memory_config, mock_llm):
            set_memory_config(MEMORY_SHORT_TERM_SIZE=5, MEMORY_COMPRESSION_THRESHOLD=100)
            manager = MemoryManager(mock_llm)
            ...
    """

    def _set_config(**kwargs):
        for key, value in kwargs.items():
            monkeypatch.setattr(Config, key, value)

    return _set_config


class MockLLM:
    """Mock LLM for testing without API calls."""

    def __init__(self, provider="mock", model="mock-model"):
        self.provider_name = provider
        self.model = model
        self.call_count = 0
        self.last_messages = None
        self.response_text = "This is a summary of the conversation."

    def call(self, messages, tools=None, max_tokens=4096, **kwargs):
        """Mock LLM call that returns a summary."""
        self.call_count += 1
        self.last_messages = messages

        return LLMResponse(
            message=self.response_text,
            stop_reason="end_turn",
            usage={"input_tokens": 100, "output_tokens": 50},
        )

    def extract_text(self, response):
        """Extract text from response."""
        if isinstance(response, LLMResponse):
            return response.message
        return response.content if hasattr(response, "content") else str(response)

    def extract_tool_calls(self, response):
        """Extract tool calls from response."""
        return []

    def format_tool_results(self, results):
        """Format tool results."""
        return LLMMessage(role="user", content=[{"type": "tool_result", "content": "result"}])

    @property
    def supports_tools(self):
        """Whether this LLM supports tools."""
        return True


@pytest.fixture
def mock_llm():
    """Create a mock LLM instance."""
    return MockLLM()


@pytest.fixture
def simple_messages():
    """Create a list of simple text messages."""
    return [
        LLMMessage(role="user", content="Hello"),
        LLMMessage(role="assistant", content="Hi there!"),
        LLMMessage(role="user", content="How are you?"),
        LLMMessage(role="assistant", content="I'm doing well, thanks!"),
    ]


@pytest.fixture
def tool_use_messages():
    """Create messages with tool_use and tool_result pairs in LiteLLM format."""
    from llm.base import ToolCall

    return [
        LLMMessage(role="user", content="Calculate 2+2"),
        LLMMessage(
            role="assistant",
            content="I'll calculate that for you.",
            tool_calls=[ToolCall(id="tool_1", name="calculator", arguments={"expression": "2+2"})],
        ),
        LLMMessage(role="user", content=[{"tool_call_id": "tool_1", "content": "4"}]),
        LLMMessage(role="assistant", content="The result is 4."),
    ]


@pytest.fixture
def protected_tool_messages():
    """Create messages with protected tool (manage_todo_list) in LiteLLM format."""
    from llm.base import ToolCall

    return [
        LLMMessage(role="user", content="Add a todo item"),
        LLMMessage(
            role="assistant",
            content="I'll add that to the todo list.",
            tool_calls=[
                ToolCall(
                    id="tool_todo_1",
                    name="manage_todo_list",
                    arguments={"action": "add", "item": "Test item"},
                )
            ],
        ),
        LLMMessage(
            role="user",
            content=[{"tool_call_id": "tool_todo_1", "content": "Todo item added"}],
        ),
        LLMMessage(role="assistant", content="Todo item has been added."),
    ]


@pytest.fixture
def mismatched_tool_messages():
    """Create messages with mismatched tool_use and tool_result (bug scenario) in LiteLLM format."""
    from llm.base import ToolCall

    return [
        LLMMessage(role="user", content="Do something"),
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="tool_1", name="tool_a", arguments={})],
        ),
        # Missing tool_result for tool_1
        LLMMessage(role="user", content="Another request"),
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="tool_2", name="tool_b", arguments={})],
        ),
        LLMMessage(
            role="user",
            content=[{"tool_call_id": "tool_2", "content": "result"}],
        ),
    ]
