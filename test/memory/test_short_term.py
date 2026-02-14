"""Unit tests for ShortTermMemory."""

from llm.base import LLMMessage
from memory.short_term import ShortTermMemory


class TestShortTermMemoryBasics:
    """Test basic ShortTermMemory functionality."""

    def test_initialization(self):
        """Test ShortTermMemory initialization."""
        stm = ShortTermMemory()

        assert stm.count() == 0

    def test_add_single_message(self):
        """Test adding a single message."""
        stm = ShortTermMemory()
        msg = LLMMessage(role="user", content="Hello")

        stm.add_message(msg)

        assert stm.count() == 1
        assert stm.get_messages()[0] == msg

    def test_add_multiple_messages(self):
        """Test adding multiple messages."""
        stm = ShortTermMemory()

        messages = [
            LLMMessage(role="user", content="Message 1"),
            LLMMessage(role="assistant", content="Response 1"),
            LLMMessage(role="user", content="Message 2"),
        ]

        for msg in messages:
            stm.add_message(msg)

        assert stm.count() == 3
        assert stm.get_messages() == messages

    def test_get_messages_returns_list(self):
        """Test that get_messages returns a list."""
        stm = ShortTermMemory()

        stm.add_message(LLMMessage(role="user", content="Hello"))

        messages = stm.get_messages()
        assert isinstance(messages, list)
        assert len(messages) == 1

    def test_get_messages_order(self):
        """Test that messages are returned in chronological order."""
        stm = ShortTermMemory()

        msg1 = LLMMessage(role="user", content="First")
        msg2 = LLMMessage(role="assistant", content="Second")
        msg3 = LLMMessage(role="user", content="Third")

        stm.add_message(msg1)
        stm.add_message(msg2)
        stm.add_message(msg3)

        messages = stm.get_messages()
        assert messages == [msg1, msg2, msg3]


class TestShortTermMemoryUnbounded:
    """Test that short-term memory grows without limit."""

    def test_no_eviction(self):
        """Test that messages are never silently evicted."""
        stm = ShortTermMemory()

        messages = []
        for i in range(200):
            msg = LLMMessage(role="user", content=f"Message {i}")
            messages.append(msg)
            stm.add_message(msg)

        assert stm.count() == 200
        assert stm.get_messages() == messages

    def test_count_accuracy(self):
        """Test that count() returns accurate count."""
        stm = ShortTermMemory()

        assert stm.count() == 0

        stm.add_message(LLMMessage(role="user", content="1"))
        assert stm.count() == 1

        stm.add_message(LLMMessage(role="user", content="2"))
        assert stm.count() == 2

        for i in range(10):
            stm.add_message(LLMMessage(role="user", content=f"Msg {i}"))

        assert stm.count() == 12


class TestShortTermMemoryClear:
    """Test clearing functionality."""

    def test_clear_empty_memory(self):
        """Test clearing empty memory."""
        stm = ShortTermMemory()

        messages = stm.clear()

        assert len(messages) == 0
        assert stm.count() == 0

    def test_clear_returns_messages(self):
        """Test that clear returns all messages."""
        stm = ShortTermMemory()

        msg1 = LLMMessage(role="user", content="First")
        msg2 = LLMMessage(role="assistant", content="Second")

        stm.add_message(msg1)
        stm.add_message(msg2)

        messages = stm.clear()

        assert len(messages) == 2
        assert messages == [msg1, msg2]

    def test_clear_empties_memory(self):
        """Test that clear empties the memory."""
        stm = ShortTermMemory()

        stm.add_message(LLMMessage(role="user", content="Message"))
        stm.clear()

        assert stm.count() == 0
        assert stm.get_messages() == []

    def test_add_after_clear(self):
        """Test adding messages after clearing."""
        stm = ShortTermMemory()

        # Add and clear
        stm.add_message(LLMMessage(role="user", content="Old"))
        stm.clear()

        # Add new messages
        new_msg = LLMMessage(role="user", content="New")
        stm.add_message(new_msg)

        messages = stm.get_messages()
        assert len(messages) == 1
        assert messages[0] == new_msg


class TestShortTermMemoryEdgeCases:
    """Test edge cases."""

    def test_message_with_complex_content(self):
        """Test adding messages with complex content."""
        stm = ShortTermMemory()

        complex_msg = LLMMessage(
            role="assistant",
            content=[
                {"type": "text", "text": "Hello"},
                {"type": "tool_use", "id": "t1", "name": "tool", "input": {"key": "value"}},
            ],
        )

        stm.add_message(complex_msg)

        messages = stm.get_messages()
        assert len(messages) == 1
        assert messages[0] == complex_msg
        assert messages[0].content == complex_msg.content

    def test_multiple_clears(self):
        """Test multiple consecutive clears."""
        stm = ShortTermMemory()

        stm.add_message(LLMMessage(role="user", content="Message"))

        stm.clear()
        stm.clear()
        stm.clear()

        assert stm.count() == 0


class TestShortTermMemoryBehavior:
    """Test specific behavioral scenarios."""

    def test_message_independence(self):
        """Test that stored messages are independent."""
        stm = ShortTermMemory()

        msg1 = LLMMessage(role="user", content="Original")
        stm.add_message(msg1)

        # Modify original message
        msg1.content = "Modified"

        # Stored message should be affected (since we store references)
        messages = stm.get_messages()
        # Note: This behavior depends on whether we do deep copy or not
        # Current implementation stores references
        assert messages[0].content == "Modified"

    def test_get_messages_returns_copy(self):
        """Test that get_messages returns a copy of the list."""
        stm = ShortTermMemory()

        stm.add_message(LLMMessage(role="user", content="Message"))

        messages1 = stm.get_messages()
        messages2 = stm.get_messages()

        # Should be different list objects
        assert messages1 is not messages2
        # But contain same messages
        assert messages1 == messages2

    def test_eviction_doesnt_affect_cleared_messages(self):
        """Test that cleared messages are preserved."""
        stm = ShortTermMemory()

        msg1 = LLMMessage(role="user", content="1")
        msg2 = LLMMessage(role="user", content="2")

        stm.add_message(msg1)
        stm.add_message(msg2)

        cleared = stm.clear()

        # Add new messages
        stm.add_message(LLMMessage(role="user", content="3"))
        stm.add_message(LLMMessage(role="user", content="4"))

        # Cleared messages should still be intact
        assert len(cleared) == 2
        assert cleared[0].content == "1"
        assert cleared[1].content == "2"

    def test_sequential_operations(self):
        """Test a sequence of mixed operations."""
        stm = ShortTermMemory()

        # Add, check, add, check, clear, add, check
        stm.add_message(LLMMessage(role="user", content="1"))
        assert stm.count() == 1

        stm.add_message(LLMMessage(role="user", content="2"))
        stm.add_message(LLMMessage(role="user", content="3"))
        assert stm.count() == 3

        stm.add_message(LLMMessage(role="user", content="4"))
        messages = stm.get_messages()
        assert len(messages) == 4

        stm.clear()
        assert stm.count() == 0

        stm.add_message(LLMMessage(role="user", content="5"))
        assert stm.count() == 1


class TestShortTermMemoryRemoveLast:
    """Test remove_last functionality."""

    def test_remove_last_single_message(self):
        """Test removing the last message."""
        stm = ShortTermMemory()
        msg1 = LLMMessage(role="user", content="First")
        msg2 = LLMMessage(role="user", content="Second")

        stm.add_message(msg1)
        stm.add_message(msg2)

        stm.remove_last(1)

        assert stm.count() == 1
        assert stm.get_messages() == [msg1]

    def test_remove_last_multiple_messages(self):
        """Test removing multiple messages from the end."""
        stm = ShortTermMemory()
        msg1 = LLMMessage(role="user", content="First")
        msg2 = LLMMessage(role="assistant", content="Second")
        msg3 = LLMMessage(role="user", content="Third")

        stm.add_message(msg1)
        stm.add_message(msg2)
        stm.add_message(msg3)

        stm.remove_last(2)

        assert stm.count() == 1
        assert stm.get_messages() == [msg1]

    def test_remove_last_more_than_available(self):
        """Test removing more messages than available."""
        stm = ShortTermMemory()
        msg1 = LLMMessage(role="user", content="First")
        msg2 = LLMMessage(role="user", content="Second")

        stm.add_message(msg1)
        stm.add_message(msg2)

        stm.remove_last(5)

        assert stm.count() == 0

    def test_remove_last_from_empty(self):
        """Test removing from empty memory (should not crash)."""
        stm = ShortTermMemory()

        stm.remove_last(1)

        assert stm.count() == 0

    def test_remove_last_zero_count(self):
        """Test removing zero messages."""
        stm = ShortTermMemory()
        msg = LLMMessage(role="user", content="Message")

        stm.add_message(msg)
        stm.remove_last(0)

        assert stm.count() == 1
        assert stm.get_messages() == [msg]
