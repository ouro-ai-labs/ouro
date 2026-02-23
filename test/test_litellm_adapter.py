"""Tests for LiteLLM adapter message conversion."""

import json
import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from config import Config
from llm.chatgpt_auth import ChatGPTLoginRequiredError
from llm.content_utils import extract_text
from llm.litellm_adapter import LiteLLMAdapter
from llm.message_types import LLMMessage


class TestMessageConversion:
    """Test message conversion in LiteLLM adapter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = LiteLLMAdapter(model="gpt-3.5-turbo")

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
        mock_message.tool_calls = None

        messages = [LLMMessage(role="assistant", content=mock_message)]

        result = self.adapter._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        # Should handle None gracefully by returning empty string
        assert result[0]["content"] == ""

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

    def test_extract_text_with_text_blocks(self):
        """Test extract_text with text blocks (using centralized function)."""
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]
        result = extract_text(content)
        assert result == "Hello\nWorld"

    def test_extract_text_with_objects_having_text_attr(self):
        """Test extract_text with objects having text attribute."""
        block1 = MagicMock()
        block1.text = "First"
        block2 = MagicMock()
        block2.text = "Second"

        content = [block1, block2]
        result = extract_text(content)
        assert result == "First\nSecond"

    def test_convert_anthropic_tool_results_to_tool_messages(self):
        """Test conversion of Anthropic tool_result format to OpenAI tool messages."""
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
        result = self.adapter._convert_anthropic_tool_results(content)

        assert len(result) == 2
        assert result[0]["role"] == "tool"
        assert result[0]["content"] == "Result data"
        assert result[0]["tool_call_id"] == "call_123"
        assert result[1]["content"] == "More results"
        assert result[1]["tool_call_id"] == "call_456"

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
        self.adapter = LiteLLMAdapter(model="gpt-3.5-turbo")

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


def test_convert_response_sanitizes_non_json_tool_arguments():
    adapter = LiteLLMAdapter(model="gpt-3.5-turbo")

    # Simulate a provider tool_call where arguments are a Python dict repr (invalid JSON).
    tc = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="TaskGetMany", arguments="{'ids': ['1', '2']}"),
    )
    message = SimpleNamespace(content=None, tool_calls=[tc], reasoning_content=None)
    choice = SimpleNamespace(message=message, finish_reason="tool_calls")
    response = SimpleNamespace(choices=[choice], usage=None)

    converted = adapter._convert_response(response)
    assert converted.tool_calls is not None
    args = converted.tool_calls[0]["function"]["arguments"]
    # Must be valid JSON string to survive strict providers.
    parsed = json.loads(args)
    assert parsed == {"ids": ["1", "2"]}


async def test_chatgpt_adapter_sets_token_dir_and_avoids_device_code(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / "auth.json").write_text(
        json.dumps({"access_token": "at_123", "expires_at": int(time.time()) + 3600}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))

    called: dict[str, object] = {"interactive": None}

    async def fake_ensure_chatgpt_access_token(*, interactive: bool) -> str:
        called["interactive"] = interactive
        return "at_123"

    monkeypatch.setattr(
        "llm.chatgpt_auth.ensure_chatgpt_access_token", fake_ensure_chatgpt_access_token
    )

    adapter = LiteLLMAdapter(model="chatgpt/gpt-5.2")
    assert os.environ.get("CHATGPT_TOKEN_DIR") == str(auth_dir)

    response = MagicMock()
    choice = MagicMock()
    message = MagicMock()
    message.content = "ok"
    message.tool_calls = None
    message.thinking_blocks = None
    message.reasoning_content = None
    choice.message = message
    choice.finish_reason = "stop"
    response.choices = [choice]
    response.usage = {"prompt_tokens": 1, "completion_tokens": 1}

    async def fake_acompletion(**_kwargs):
        return response

    fake_litellm = SimpleNamespace(
        acompletion=fake_acompletion,
        drop_params=None,
        set_verbose=None,
        suppress_debug_info=None,
    )
    monkeypatch.setattr(adapter, "_get_litellm", lambda: fake_litellm)

    result = await adapter.call_async([LLMMessage(role="user", content="hi")])

    assert called["interactive"] is False
    assert result.content == "ok"


async def test_chatgpt_adapter_errors_fast_when_not_logged_in(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))

    async def fake_ensure_chatgpt_access_token(*, interactive: bool) -> str:  # noqa: ARG001
        raise ChatGPTLoginRequiredError("not logged in")

    monkeypatch.setattr(
        "llm.chatgpt_auth.ensure_chatgpt_access_token", fake_ensure_chatgpt_access_token
    )

    adapter = LiteLLMAdapter(model="chatgpt/gpt-5.2")
    monkeypatch.setattr(adapter, "_get_litellm", lambda: (_ for _ in ()).throw(AssertionError()))

    with pytest.raises(RuntimeError, match=r"Run `/login`"):
        await adapter.call_async([LLMMessage(role="user", content="hi")])


async def test_chatgpt_adapter_preserves_non_login_auth_errors(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))

    async def fake_ensure_chatgpt_access_token(*, interactive: bool) -> str:  # noqa: ARG001
        raise RuntimeError("refresh endpoint timeout")

    monkeypatch.setattr(
        "llm.chatgpt_auth.ensure_chatgpt_access_token", fake_ensure_chatgpt_access_token
    )

    adapter = LiteLLMAdapter(model="chatgpt/gpt-5.2")
    monkeypatch.setattr(adapter, "_get_litellm", lambda: (_ for _ in ()).throw(AssertionError()))

    with pytest.raises(RuntimeError, match="refresh endpoint timeout"):
        await adapter.call_async([LLMMessage(role="user", content="hi")])


async def test_chatgpt_adapter_retries_transient_auth_refresh_errors(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))
    monkeypatch.setattr(Config, "get_retry_delay", lambda attempt: 0.0)

    calls = {"count": 0}

    async def fake_ensure_chatgpt_access_token(*, interactive: bool) -> str:
        assert interactive is False
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("timeout")
        return "at_123"

    monkeypatch.setattr(
        "llm.chatgpt_auth.ensure_chatgpt_access_token", fake_ensure_chatgpt_access_token
    )

    response = MagicMock()
    choice = MagicMock()
    message = MagicMock()
    message.content = "ok"
    message.tool_calls = None
    message.thinking_blocks = None
    message.reasoning_content = None
    choice.message = message
    choice.finish_reason = "stop"
    response.choices = [choice]
    response.usage = {"prompt_tokens": 1, "completion_tokens": 1}

    async def fake_acompletion(**_kwargs):
        return response

    fake_litellm = SimpleNamespace(
        acompletion=fake_acompletion,
        drop_params=None,
        set_verbose=None,
        suppress_debug_info=None,
    )

    adapter = LiteLLMAdapter(model="chatgpt/gpt-5.2")
    monkeypatch.setattr(adapter, "_get_litellm", lambda: fake_litellm)

    result = await adapter.call_async([LLMMessage(role="user", content="hi")])

    assert calls["count"] >= 2
    assert result.content == "ok"
