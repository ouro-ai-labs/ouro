"""Tests for LiteLLM adapter message conversion."""

import json
from unittest.mock import MagicMock

import pytest

from llm.base import LLMMessage
from llm.litellm_adapter import LiteLLMLLM


class TestMessageConversion:
    """Test message conversion in LiteLLM adapter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = LiteLLMLLM(model="gpt-3.5-turbo")

    def test_convert_simple_string_content(self):
        """Test conversion of simple string content."""
        messages = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi there!"),
        ]
        result = self.adapter._convert_messages(messages)

        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "Hello"}
        assert result[1] == {"role": "assistant", "content": "Hi there!"}

    def test_extract_content_from_nested_message_object(self):
        """Test extraction of content from nested Message objects.

        This tests the fix for the issue where Message objects were being
        stringified instead of having their content extracted.
        """
        # Create a mock Message object (simulating LiteLLM response)
        mock_message = MagicMock()
        mock_message.content = "This is the actual content"
        mock_message.role = "assistant"
        mock_message.tool_calls = None

        # Create an LLMMessage with the mock Message as content
        messages = [LLMMessage(role="assistant", content=mock_message)]

        result = self.adapter._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        # Should extract the content, not stringify the entire object
        assert result[0]["content"] == "This is the actual content"
        assert "Message(" not in result[0]["content"]

    def test_extract_content_from_deeply_nested_message_objects(self):
        """Test extraction from multiple levels of nested Message objects."""
        # Create deeply nested mock Message objects
        innermost_message = MagicMock()
        innermost_message.content = "Deep content"
        innermost_message.role = "assistant"

        middle_message = MagicMock()
        middle_message.content = innermost_message
        middle_message.role = "assistant"

        outer_message = MagicMock()
        outer_message.content = middle_message
        outer_message.role = "assistant"

        messages = [LLMMessage(role="assistant", content=outer_message)]

        result = self.adapter._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        # Should recursively extract until reaching the actual content
        assert result[0]["content"] == "Deep content"
        assert "Message(" not in result[0]["content"]

    def test_extract_content_from_message_with_none_content(self):
        """Test handling of Message objects with None content."""
        mock_message = MagicMock()
        mock_message.content = None
        mock_message.role = "assistant"

        messages = [LLMMessage(role="assistant", content=mock_message)]

        result = self.adapter._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        # Should handle None gracefully
        assert result[0]["content"] == "None"

    def test_extract_content_from_message_with_list_content(self):
        """Test extraction from Message with list content (Anthropic format)."""
        # Create a mock Message with list content
        mock_message = MagicMock()
        mock_message.content = [
            {"type": "text", "text": "First block"},
            {"type": "text", "text": "Second block"},
        ]
        mock_message.role = "assistant"

        messages = [LLMMessage(role="assistant", content=mock_message)]

        result = self.adapter._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        # Should extract text from all blocks
        assert "First block" in result[0]["content"]
        assert "Second block" in result[0]["content"]

    def test_extract_assistant_content_with_text_blocks(self):
        """Test _extract_assistant_content with text blocks."""
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]
        result = self.adapter._extract_assistant_content(content)
        assert result == "Hello\nWorld"

    def test_extract_assistant_content_with_objects_having_text_attr(self):
        """Test _extract_assistant_content with objects having text attribute."""
        block1 = MagicMock()
        block1.text = "First"
        block2 = MagicMock()
        block2.text = "Second"

        content = [block1, block2]
        result = self.adapter._extract_assistant_content(content)
        assert result == "First\nSecond"

    def test_convert_tool_results_to_text(self):
        """Test conversion of tool results to text format."""
        content = [
            {
                "type": "tool_result",
                "tool_use_id": "call_123",
                "content": "Result data",
            },
            {
                "type": "tool_result",
                "tool_use_id": "call_456",
                "content": "More results",
            },
        ]
        result = self.adapter._convert_tool_results_to_text(content)

        assert "call_123" in result
        assert "Result data" in result
        assert "call_456" in result
        assert "More results" in result

    def test_mixed_message_types(self):
        """Test conversion of mixed message types."""
        mock_message = MagicMock()
        mock_message.content = "Assistant response"

        messages = [
            LLMMessage(role="system", content="You are helpful"),
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content=mock_message),
            LLMMessage(role="user", content="Follow up"),
        ]

        result = self.adapter._convert_messages(messages)

        assert len(result) == 4
        assert result[0] == {"role": "system", "content": "You are helpful"}
        assert result[1] == {"role": "user", "content": "Hello"}
        assert result[2] == {"role": "assistant", "content": "Assistant response"}
        assert result[3] == {"role": "user", "content": "Follow up"}


class TestToolConversion:
    """Test tool conversion in LiteLLM adapter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = LiteLLMLLM(model="gpt-3.5-turbo")

    def test_convert_tools_to_openai_format(self):
        """Test conversion of Anthropic tool format to OpenAI format."""
        tools = [
            {
                "name": "read_file",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            }
        ]

        result = self.adapter._convert_tools(tools)

        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "read_file"
        assert result[0]["function"]["description"] == "Read a file"
        assert result[0]["function"]["parameters"] == tools[0]["input_schema"]
