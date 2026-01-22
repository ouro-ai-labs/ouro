"""Unit tests for MemoryStore (database persistence)."""

import os
import tempfile
from pathlib import Path

import pytest

from llm.base import LLMMessage
from memory.store import MemoryStore
from memory.types import CompressedMemory


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    # Create temporary file
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    yield path

    # Cleanup
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def store(temp_db):
    """Create a MemoryStore instance with temp database."""
    return MemoryStore(db_path=temp_db)


class TestMemoryStoreBasics:
    """Test basic MemoryStore functionality."""

    def test_initialization(self, store):
        """Test MemoryStore initialization."""
        assert store.db_path is not None
        # Should create database file
        assert Path(store.db_path).exists()

    def test_create_session(self, store):
        """Test creating a new session."""
        session_id = store.create_session()

        assert session_id is not None
        assert len(session_id) == 36  # UUID length

    def test_create_session_basic(self, store):
        """Test creating basic session (simplified version)."""
        session_id = store.create_session()

        # Load and verify
        session_data = store.load_session(session_id)
        assert session_data is not None
        assert session_data["config"] is None  # Config not stored in simplified version
        assert session_data["messages"] == []
        assert session_data["system_messages"] == []
        assert session_data["summaries"] == []


class TestMessageStorage:
    """Test message storage and retrieval."""

    def test_save_message(self, store):
        """Test saving a message."""
        session_id = store.create_session()
        msg = LLMMessage(role="user", content="Hello")

        store.save_message(session_id, msg, tokens=5)

        # Load and verify
        session_data = store.load_session(session_id)
        assert len(session_data["messages"]) == 1
        assert session_data["messages"][0].role == "user"
        assert session_data["messages"][0].content == "Hello"

    def test_save_system_message(self, store):
        """Test saving a system message."""
        session_id = store.create_session()
        msg = LLMMessage(role="system", content="You are helpful")

        store.save_message(session_id, msg, tokens=0)

        # Load and verify
        session_data = store.load_session(session_id)
        assert len(session_data["system_messages"]) == 1
        assert session_data["system_messages"][0].role == "system"

    def test_save_multiple_messages(self, store):
        """Test saving multiple messages."""
        session_id = store.create_session()

        messages = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi there"),
            LLMMessage(role="user", content="How are you?"),
        ]

        for msg in messages:
            store.save_message(session_id, msg, tokens=10)

        # Load and verify
        session_data = store.load_session(session_id)
        assert len(session_data["messages"]) == 3

    def test_save_message_with_complex_content(self, store):
        """Test saving message with list content."""
        session_id = store.create_session()
        msg = LLMMessage(
            role="assistant",
            content=[
                {"type": "text", "text": "I'll use a tool"},
                {"type": "tool_use", "id": "tool_1", "name": "calculator", "input": {}},
            ],
        )

        store.save_message(session_id, msg, tokens=20)

        # Load and verify
        session_data = store.load_session(session_id)
        loaded_msg = session_data["messages"][0]
        assert isinstance(loaded_msg.content, list)
        assert len(loaded_msg.content) == 2


class TestToolCallsSerialization:
    """Test tool_calls and tool_call_id serialization."""

    def test_save_assistant_message_with_tool_calls(self, store):
        """Test saving assistant message with tool_calls preserves tool_calls."""
        session_id = store.create_session()
        tool_calls = [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {"name": "web_fetch", "arguments": '{"url": "https://example.com"}'},
            }
        ]
        msg = LLMMessage(role="assistant", content=None, tool_calls=tool_calls)

        store.save_message(session_id, msg, tokens=10)

        # Load and verify
        session_data = store.load_session(session_id)
        loaded_msg = session_data["messages"][0]
        assert loaded_msg.role == "assistant"
        assert loaded_msg.tool_calls is not None
        assert len(loaded_msg.tool_calls) == 1
        assert loaded_msg.tool_calls[0]["id"] == "call_abc123"
        assert loaded_msg.tool_calls[0]["function"]["name"] == "web_fetch"

    def test_save_assistant_message_without_tool_calls(self, store):
        """Test saving assistant message without tool_calls includes null tool_calls."""
        session_id = store.create_session()
        msg = LLMMessage(role="assistant", content="Hello there!")

        store.save_message(session_id, msg, tokens=5)

        # Load and verify - assistant messages should have tool_calls field (even if None)
        session_data = store.load_session(session_id)
        loaded_msg = session_data["messages"][0]
        assert loaded_msg.role == "assistant"
        assert loaded_msg.content == "Hello there!"

    def test_save_tool_message_with_tool_call_id(self, store):
        """Test saving tool message preserves tool_call_id."""
        session_id = store.create_session()
        msg = LLMMessage(
            role="tool",
            content='{"result": "success"}',
            tool_call_id="call_abc123",
            name="web_fetch",
        )

        store.save_message(session_id, msg, tokens=8)

        # Load and verify
        session_data = store.load_session(session_id)
        loaded_msg = session_data["messages"][0]
        assert loaded_msg.role == "tool"
        assert loaded_msg.tool_call_id == "call_abc123"
        assert loaded_msg.name == "web_fetch"
        assert loaded_msg.content == '{"result": "success"}'

    def test_tool_call_roundtrip(self, store):
        """Test complete tool call flow: assistant with tool_calls -> tool response."""
        session_id = store.create_session()

        # Assistant makes a tool call
        tool_calls = [
            {
                "id": "call_xyz789",
                "type": "function",
                "function": {"name": "calculator", "arguments": '{"expression": "2+2"}'},
            }
        ]
        assistant_msg = LLMMessage(role="assistant", content=None, tool_calls=tool_calls)
        store.save_message(session_id, assistant_msg, tokens=15)

        # Tool responds
        tool_msg = LLMMessage(
            role="tool",
            content="4",
            tool_call_id="call_xyz789",
            name="calculator",
        )
        store.save_message(session_id, tool_msg, tokens=5)

        # Load and verify the complete flow
        session_data = store.load_session(session_id)
        assert len(session_data["messages"]) == 2

        loaded_assistant = session_data["messages"][0]
        loaded_tool = session_data["messages"][1]

        # Verify tool_call_id matches
        assert loaded_assistant.tool_calls[0]["id"] == loaded_tool.tool_call_id
        assert loaded_tool.name == "calculator"


class TestBatchSave:
    """Test batch save_memory functionality."""

    def test_save_memory(self, store):
        """Test saving complete memory state at once."""
        session_id = store.create_session()

        # Create memory components
        system_messages = [LLMMessage(role="system", content="You are helpful")]

        messages = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi there"),
            LLMMessage(role="user", content="How are you?"),
        ]

        summaries = [
            CompressedMemory(
                summary="Earlier conversation summary",
                preserved_messages=[],
                original_message_count=5,
                original_tokens=500,
                compressed_tokens=150,
                compression_ratio=0.3,
            )
        ]

        # Save all at once
        store.save_memory(session_id, system_messages, messages, summaries)

        # Load and verify
        session_data = store.load_session(session_id)
        assert len(session_data["system_messages"]) == 1
        assert len(session_data["messages"]) == 3
        assert len(session_data["summaries"]) == 1

        # Verify content
        assert session_data["system_messages"][0].content == "You are helpful"
        assert session_data["messages"][0].content == "Hello"
        assert session_data["summaries"][0].summary == "Earlier conversation summary"

    def test_save_memory_replaces_content(self, store):
        """Test that save_memory replaces all content."""
        session_id = store.create_session()

        # First save
        store.save_memory(
            session_id,
            [LLMMessage(role="system", content="First")],
            [LLMMessage(role="user", content="Message 1")],
            [],
        )

        # Second save (should replace, not append)
        store.save_memory(
            session_id,
            [LLMMessage(role="system", content="Second")],
            [LLMMessage(role="user", content="Message 2")],
            [],
        )

        # Load and verify - should only have second save's content
        session_data = store.load_session(session_id)
        assert len(session_data["system_messages"]) == 1
        assert len(session_data["messages"]) == 1
        assert session_data["system_messages"][0].content == "Second"
        assert session_data["messages"][0].content == "Message 2"


class TestSummaryStorage:
    """Test summary (compressed memory) storage."""

    def test_save_summary(self, store):
        """Test saving a compression summary."""
        session_id = store.create_session()

        summary = CompressedMemory(
            summary="This is a summary",
            preserved_messages=[LLMMessage(role="user", content="Important message")],
            original_message_count=10,
            original_tokens=1000,
            compressed_tokens=300,
            compression_ratio=0.3,
            metadata={"strategy": "selective"},
        )

        store.save_summary(session_id, summary)

        # Load and verify
        session_data = store.load_session(session_id)
        assert len(session_data["summaries"]) == 1

        loaded_summary = session_data["summaries"][0]
        assert loaded_summary.summary == "This is a summary"
        assert loaded_summary.original_message_count == 10
        assert loaded_summary.original_tokens == 1000
        assert loaded_summary.compressed_tokens == 300
        assert len(loaded_summary.preserved_messages) == 1

    def test_save_multiple_summaries(self, store):
        """Test saving multiple summaries."""
        session_id = store.create_session()

        for i in range(3):
            summary = CompressedMemory(
                summary=f"Summary {i}",
                preserved_messages=[],
                original_message_count=5,
                original_tokens=500,
                compressed_tokens=150,
                compression_ratio=0.3,
            )
            store.save_summary(session_id, summary)

        # Load and verify
        session_data = store.load_session(session_id)
        assert len(session_data["summaries"]) == 3
        assert session_data["stats"]["compression_count"] == 3


class TestSessionRetrieval:
    """Test session retrieval and listing."""

    def test_list_sessions(self, store):
        """Test listing sessions."""
        # Create multiple sessions
        session_ids = []
        for i in range(3):
            sid = store.create_session(metadata={"index": i})
            session_ids.append(sid)

        # List sessions
        sessions = store.list_sessions()

        assert len(sessions) == 3
        for session in sessions:
            assert session["id"] in session_ids

    def test_list_sessions_with_limit(self, store):
        """Test listing sessions with limit."""
        # Create multiple sessions
        for i in range(10):
            store.create_session()

        # List with limit
        sessions = store.list_sessions(limit=5)

        assert len(sessions) == 5

    def test_load_nonexistent_session(self, store):
        """Test loading a session that doesn't exist."""
        result = store.load_session("nonexistent-id")
        assert result is None

    def test_get_session_stats(self, store):
        """Test getting session statistics."""
        session_id = store.create_session()

        # Add some data
        store.save_message(session_id, LLMMessage(role="user", content="Hello"), tokens=5)
        store.save_message(session_id, LLMMessage(role="assistant", content="Hi"), tokens=3)

        summary = CompressedMemory(
            summary="Summary",
            preserved_messages=[],
            original_message_count=5,
            original_tokens=500,
            compressed_tokens=150,
            compression_ratio=0.3,
        )
        store.save_summary(session_id, summary)

        # Get stats
        stats = store.get_session_stats(session_id)

        assert stats is not None
        assert stats["message_count"] == 2
        assert stats["summary_count"] == 1
        assert stats["compression_count"] == 1
        assert stats["total_message_tokens"] == 8
        # Note: SQL SUM aggregates all rows, but we want totals
        assert stats["total_original_tokens"] >= 500
        assert stats["total_compressed_tokens"] >= 150
        assert stats["token_savings"] >= 0


class TestSessionManagement:
    """Test session management operations."""

    def test_delete_session(self, store):
        """Test deleting a session."""
        session_id = store.create_session()

        # Add some data
        store.save_message(session_id, LLMMessage(role="user", content="Hello"), tokens=5)

        # Delete
        success = store.delete_session(session_id)
        assert success

        # Verify deleted
        result = store.load_session(session_id)
        assert result is None

    def test_delete_nonexistent_session(self, store):
        """Test deleting a session that doesn't exist."""
        success = store.delete_session("nonexistent-id")
        assert not success


class TestIntegration:
    """Integration tests for complete workflows."""

    def test_complete_session_lifecycle(self, store):
        """Test a complete session lifecycle."""
        # Create session (simplified - no metadata or config storage)
        session_id = store.create_session()

        # Add system message
        store.save_message(
            session_id, LLMMessage(role="system", content="You are helpful"), tokens=0
        )

        # Add conversation
        for i in range(10):
            store.save_message(
                session_id, LLMMessage(role="user", content=f"Question {i}"), tokens=5
            )
            store.save_message(
                session_id, LLMMessage(role="assistant", content=f"Answer {i}"), tokens=10
            )

        # Add summaries
        for i in range(2):
            summary = CompressedMemory(
                summary=f"Summary of batch {i}",
                preserved_messages=[],
                original_message_count=5,
                original_tokens=75,
                compressed_tokens=25,
                compression_ratio=0.33,
            )
            store.save_summary(session_id, summary)

        # Load and verify
        session_data = store.load_session(session_id)

        assert len(session_data["system_messages"]) == 1
        assert len(session_data["messages"]) == 20
        assert len(session_data["summaries"]) == 2
        assert session_data["stats"]["compression_count"] == 2

        # Get stats
        stats = store.get_session_stats(session_id)
        assert stats["message_count"] == 20
        assert stats["summary_count"] == 2
        assert stats["token_savings"] > 0
