"""Unit tests for YamlFileMemoryStore (YAML file persistence)."""

import os
import tempfile

import pytest

from llm.message_types import LLMMessage
from memory.store import YamlFileMemoryStore


@pytest.fixture
def temp_sessions_dir():
    """Create a temporary sessions directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sessions_dir = os.path.join(tmpdir, "sessions")
        yield sessions_dir


@pytest.fixture
def store(temp_sessions_dir):
    """Create a YamlFileMemoryStore instance with temp directory."""
    return YamlFileMemoryStore(sessions_dir=temp_sessions_dir)


class TestYamlBackendBasics:
    """Test basic YamlFileMemoryStore functionality."""

    async def test_create_session(self, store):
        """Test creating a new session."""
        session_id = await store.create_session()

        assert session_id is not None
        assert len(session_id) == 36  # UUID length

    async def test_create_session_creates_directory(self, store, temp_sessions_dir):
        """Test that creating a session creates a directory with session.yaml."""
        await store.create_session()

        # Check that sessions dir and session subdir exist
        assert os.path.exists(temp_sessions_dir)
        entries = os.listdir(temp_sessions_dir)
        # Filter out .index.yaml
        dirs = [e for e in entries if not e.startswith(".")]
        assert len(dirs) == 1

        # Check session.yaml exists
        session_yaml = os.path.join(temp_sessions_dir, dirs[0], "session.yaml")
        assert os.path.exists(session_yaml)

    async def test_create_session_basic(self, store):
        """Test creating basic session and loading it."""
        session_id = await store.create_session()

        session_data = await store.load_session(session_id)
        assert session_data is not None
        assert session_data["config"] is None
        assert session_data["messages"] == []
        assert session_data["system_messages"] == []


class TestMessageStorage:
    """Test message storage and retrieval."""

    async def test_save_message(self, store):
        """Test saving a message."""
        session_id = await store.create_session()
        msg = LLMMessage(role="user", content="Hello")

        await store.save_message(session_id, msg, tokens=5)

        session_data = await store.load_session(session_id)
        assert len(session_data["messages"]) == 1
        assert session_data["messages"][0].role == "user"
        assert session_data["messages"][0].content == "Hello"

    async def test_save_system_message(self, store):
        """Test saving a system message."""
        session_id = await store.create_session()
        msg = LLMMessage(role="system", content="You are helpful")

        await store.save_message(session_id, msg, tokens=0)

        session_data = await store.load_session(session_id)
        assert len(session_data["system_messages"]) == 1
        assert session_data["system_messages"][0].role == "system"

    async def test_save_multiple_messages(self, store):
        """Test saving multiple messages."""
        session_id = await store.create_session()

        messages = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi there"),
            LLMMessage(role="user", content="How are you?"),
        ]

        for msg in messages:
            await store.save_message(session_id, msg, tokens=10)

        session_data = await store.load_session(session_id)
        assert len(session_data["messages"]) == 3


class TestToolCallsSerialization:
    """Test tool_calls and tool_call_id serialization."""

    async def test_save_assistant_message_with_tool_calls(self, store):
        """Test saving assistant message with tool_calls."""
        session_id = await store.create_session()
        tool_calls = [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {"name": "web_fetch", "arguments": '{"url": "https://example.com"}'},
            }
        ]
        msg = LLMMessage(role="assistant", content=None, tool_calls=tool_calls)

        await store.save_message(session_id, msg, tokens=10)

        session_data = await store.load_session(session_id)
        loaded_msg = session_data["messages"][0]
        assert loaded_msg.role == "assistant"
        assert loaded_msg.tool_calls is not None
        assert len(loaded_msg.tool_calls) == 1
        assert loaded_msg.tool_calls[0]["id"] == "call_abc123"

    async def test_save_tool_message_with_tool_call_id(self, store):
        """Test saving tool message preserves tool_call_id."""
        session_id = await store.create_session()
        msg = LLMMessage(
            role="tool",
            content='{"result": "success"}',
            tool_call_id="call_abc123",
            name="web_fetch",
        )

        await store.save_message(session_id, msg, tokens=8)

        session_data = await store.load_session(session_id)
        loaded_msg = session_data["messages"][0]
        assert loaded_msg.role == "tool"
        assert loaded_msg.tool_call_id == "call_abc123"
        assert loaded_msg.name == "web_fetch"

    async def test_tool_call_roundtrip(self, store):
        """Test complete tool call flow: assistant with tool_calls -> tool response."""
        session_id = await store.create_session()

        tool_calls = [
            {
                "id": "call_xyz789",
                "type": "function",
                "function": {"name": "calculator", "arguments": '{"expression": "2+2"}'},
            }
        ]
        assistant_msg = LLMMessage(role="assistant", content=None, tool_calls=tool_calls)
        await store.save_message(session_id, assistant_msg, tokens=15)

        tool_msg = LLMMessage(
            role="tool",
            content="4",
            tool_call_id="call_xyz789",
            name="calculator",
        )
        await store.save_message(session_id, tool_msg, tokens=5)

        session_data = await store.load_session(session_id)
        assert len(session_data["messages"]) == 2

        loaded_assistant = session_data["messages"][0]
        loaded_tool = session_data["messages"][1]
        assert loaded_assistant.tool_calls[0]["id"] == loaded_tool.tool_call_id


class TestBatchSave:
    """Test batch save_memory functionality."""

    async def test_save_memory(self, store):
        """Test saving complete memory state at once."""
        session_id = await store.create_session()

        system_messages = [LLMMessage(role="system", content="You are helpful")]
        messages = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi there"),
            LLMMessage(role="user", content="How are you?"),
        ]

        await store.save_memory(session_id, system_messages, messages)

        session_data = await store.load_session(session_id)
        assert len(session_data["system_messages"]) == 1
        assert len(session_data["messages"]) == 3
        assert session_data["system_messages"][0].content == "You are helpful"

    async def test_save_memory_replaces_content(self, store):
        """Test that save_memory replaces all content."""
        session_id = await store.create_session()

        await store.save_memory(
            session_id,
            [LLMMessage(role="system", content="First")],
            [LLMMessage(role="user", content="Message 1")],
        )

        await store.save_memory(
            session_id,
            [LLMMessage(role="system", content="Second")],
            [LLMMessage(role="user", content="Message 2")],
        )

        session_data = await store.load_session(session_id)
        assert len(session_data["system_messages"]) == 1
        assert len(session_data["messages"]) == 1
        assert session_data["system_messages"][0].content == "Second"
        assert session_data["messages"][0].content == "Message 2"


class TestSessionRetrieval:
    """Test session retrieval and listing."""

    async def test_list_sessions(self, store):
        """Test listing sessions."""
        session_ids = []
        for i in range(3):
            sid = await store.create_session(metadata={"index": i})
            session_ids.append(sid)

        sessions = await store.list_sessions()
        assert len(sessions) == 3
        listed_ids = {s["id"] for s in sessions}
        assert listed_ids == set(session_ids)

    async def test_list_sessions_with_limit(self, store):
        """Test listing sessions with limit."""
        for _ in range(10):
            await store.create_session()

        sessions = await store.list_sessions(limit=5)
        assert len(sessions) == 5

    async def test_load_nonexistent_session(self, store):
        """Test loading a session that doesn't exist."""
        result = await store.load_session("nonexistent-id")
        assert result is None

    async def test_get_session_stats(self, store):
        """Test getting session statistics."""
        session_id = await store.create_session()

        messages = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi"),
        ]
        await store.save_memory(session_id, [], messages)

        stats = await store.get_session_stats(session_id)
        assert stats is not None
        assert stats["message_count"] == 2


class TestSessionManagement:
    """Test session management operations."""

    async def test_delete_session(self, store, temp_sessions_dir):
        """Test deleting a session."""
        session_id = await store.create_session()
        await store.save_message(session_id, LLMMessage(role="user", content="Hello"), tokens=5)

        success = await store.delete_session(session_id)
        assert success

        result = await store.load_session(session_id)
        assert result is None

    async def test_delete_nonexistent_session(self, store):
        """Test deleting a session that doesn't exist."""
        success = await store.delete_session("nonexistent-id")
        assert not success

    async def test_find_latest_session(self, store):
        """Test finding the most recent session."""
        await store.create_session()
        sid2 = await store.create_session()

        # Add a message to sid2 to make its updated_at more recent
        await store.save_message(sid2, LLMMessage(role="user", content="Latest"), tokens=5)

        latest = await store.find_latest_session()
        assert latest == sid2

    async def test_find_session_by_prefix(self, store):
        """Test finding a session by ID prefix."""
        session_id = await store.create_session()

        prefix = session_id[:8]
        found = await store.find_session_by_prefix(prefix)
        assert found == session_id

    async def test_find_session_by_prefix_not_found(self, store):
        """Test prefix search with no matches."""
        await store.create_session()
        found = await store.find_session_by_prefix("zzzzz")
        assert found is None


class TestSessionPreview:
    """Test session preview in list."""

    async def test_list_includes_preview(self, store):
        """Test that list_sessions includes first user message as preview."""
        session_id = await store.create_session()
        await store.save_message(
            session_id, LLMMessage(role="user", content="What is 2+2?"), tokens=5
        )

        sessions = await store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["preview"] == "What is 2+2?"


class TestIntegration:
    """Integration tests for complete workflows."""

    async def test_complete_session_lifecycle(self, store):
        """Test a complete session lifecycle."""
        session_id = await store.create_session()

        system_messages = [LLMMessage(role="system", content="You are helpful")]

        messages = []
        for i in range(10):
            messages.append(LLMMessage(role="user", content=f"Question {i}"))
            messages.append(LLMMessage(role="assistant", content=f"Answer {i}"))

        await store.save_memory(session_id, system_messages, messages)

        session_data = await store.load_session(session_id)
        assert len(session_data["system_messages"]) == 1
        assert len(session_data["messages"]) == 20

        stats = await store.get_session_stats(session_id)
        assert stats["message_count"] == 20
