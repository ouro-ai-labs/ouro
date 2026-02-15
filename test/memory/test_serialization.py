"""Unit tests for memory serialization module."""

from llm.message_types import LLMMessage
from memory.serialization import (
    deserialize_message,
    serialize_content,
    serialize_message,
)


class TestSerializeContent:
    """Test content serialization."""

    def test_none(self):
        assert serialize_content(None) is None

    def test_string(self):
        assert serialize_content("hello") == "hello"

    def test_list(self):
        data = [{"type": "text", "text": "hi"}]
        assert serialize_content(data) == data

    def test_dict(self):
        data = {"key": "value"}
        assert serialize_content(data) == data

    def test_non_serializable(self):
        result = serialize_content(object())
        assert isinstance(result, str)


class TestSerializeMessage:
    """Test LLMMessage serialization."""

    def test_user_message(self):
        msg = LLMMessage(role="user", content="Hello")
        result = serialize_message(msg)
        assert result["role"] == "user"
        assert result["content"] == "Hello"
        assert "tool_calls" not in result

    def test_assistant_message_without_tool_calls(self):
        msg = LLMMessage(role="assistant", content="Hi there!")
        result = serialize_message(msg)
        assert result["role"] == "assistant"
        assert result["content"] == "Hi there!"
        assert result["tool_calls"] is None

    def test_assistant_message_with_tool_calls(self):
        tool_calls = [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {"name": "calc", "arguments": '{"x": 1}'},
            }
        ]
        msg = LLMMessage(role="assistant", content=None, tool_calls=tool_calls)
        result = serialize_message(msg)
        assert result["role"] == "assistant"
        assert result["content"] is None
        assert result["tool_calls"] == tool_calls

    def test_tool_message(self):
        msg = LLMMessage(role="tool", content="4", tool_call_id="call_abc123", name="calculator")
        result = serialize_message(msg)
        assert result["role"] == "tool"
        assert result["content"] == "4"
        assert result["tool_call_id"] == "call_abc123"
        assert result["name"] == "calculator"

    def test_system_message(self):
        msg = LLMMessage(role="system", content="You are helpful.")
        result = serialize_message(msg)
        assert result["role"] == "system"
        assert result["content"] == "You are helpful."


class TestDeserializeMessage:
    """Test LLMMessage deserialization."""

    def test_user_message(self):
        data = {"role": "user", "content": "Hello"}
        msg = deserialize_message(data)
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_assistant_with_tool_calls(self):
        data = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "test"}}],
        }
        msg = deserialize_message(data)
        assert msg.role == "assistant"
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1

    def test_tool_message(self):
        data = {
            "role": "tool",
            "content": "result",
            "tool_call_id": "call_1",
            "name": "test_tool",
        }
        msg = deserialize_message(data)
        assert msg.role == "tool"
        assert msg.tool_call_id == "call_1"
        assert msg.name == "test_tool"


class TestRoundTrip:
    """Test serialize -> deserialize roundtrip."""

    def test_message_roundtrip(self):
        original = LLMMessage(role="tool", content="result", tool_call_id="call_1", name="calc")
        data = serialize_message(original)
        restored = deserialize_message(data)
        assert restored.role == original.role
        assert restored.content == original.content
        assert restored.tool_call_id == original.tool_call_id
        assert restored.name == original.name
