"""Unit tests for ShortTermMemory."""

from llm.base import LLMMessage
from memory.short_term import ShortTermMemory


class TestShortTermMemoryBasics:
    """Test basic ShortTermMemory functionality."""

    def test_initialization(self):
        """Test ShortTermMemory initialization."""
        stm = ShortTermMemory(max_size=10)

        assert stm.max_size == 10
        assert stm.count() == 0
        assert not stm.is_full()

    def test_initialization_default_size(self):
        """Test default initialization."""
        stm = ShortTermMemory()

        assert stm.max_size == 20  # Default value
        assert stm.count() == 0

    def test_add_single_message(self):
        """Test adding a single message."""
        stm = ShortTermMemory(max_size=5)
        msg = LLMMessage(role="user", content="Hello")

        stm.add_message(msg)

        assert stm.count() == 1
        assert stm.get_messages()[0] == msg

    def test_add_multiple_messages(self):
        """Test adding multiple messages."""
        stm = ShortTermMemory(max_size=5)

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
        stm = ShortTermMemory(max_size=5)

        stm.add_message(LLMMessage(role="user", content="Hello"))

        messages = stm.get_messages()
        assert isinstance(messages, list)
        assert len(messages) == 1

    def test_get_messages_order(self):
        """Test that messages are returned in chronological order."""
        stm = ShortTermMemory(max_size=5)

        msg1 = LLMMessage(role="user", content="First")
        msg2 = LLMMessage(role="assistant", content="Second")
        msg3 = LLMMessage(role="user", content="Third")

        stm.add_message(msg1)
        stm.add_message(msg2)
        stm.add_message(msg3)

        messages = stm.get_messages()
        assert messages == [msg1, msg2, msg3]


class TestShortTermMemoryCapacity:
    """Test capacity management."""

    def test_is_full_when_empty(self):
        """Test is_full returns False when empty."""
        stm = ShortTermMemory(max_size=3)

        assert not stm.is_full()

    def test_is_full_when_at_capacity(self):
        """Test is_full returns True at capacity."""
        stm = ShortTermMemory(max_size=3)

        for i in range(3):
            stm.add_message(LLMMessage(role="user", content=f"Message {i}"))

        assert stm.is_full()

    def test_is_full_after_overflow(self):
        """Test is_full remains True after overflow."""
        stm = ShortTermMemory(max_size=3)

        for i in range(5):  # Add more than capacity
            stm.add_message(LLMMessage(role="user", content=f"Message {i}"))

        assert stm.is_full()
        assert stm.count() == 3  # Should stay at max_size

    def test_automatic_eviction_on_overflow(self):
        """Test that oldest messages are automatically evicted."""
        stm = ShortTermMemory(max_size=3)

        msg1 = LLMMessage(role="user", content="First")
        msg2 = LLMMessage(role="user", content="Second")
        msg3 = LLMMessage(role="user", content="Third")
        msg4 = LLMMessage(role="user", content="Fourth")

        stm.add_message(msg1)
        stm.add_message(msg2)
        stm.add_message(msg3)
        stm.add_message(msg4)  # This should evict msg1

        messages = stm.get_messages()
        assert len(messages) == 3
        assert msg1 not in messages  # First message evicted
        assert msg2 in messages
        assert msg3 in messages
        assert msg4 in messages

    def test_eviction_order_fifo(self):
        """Test that eviction follows FIFO (First In, First Out)."""
        stm = ShortTermMemory(max_size=2)

        messages = []
        for i in range(5):
            msg = LLMMessage(role="user", content=f"Message {i}")
            messages.append(msg)
            stm.add_message(msg)

        # Only last 2 messages should remain
        remaining = stm.get_messages()
        assert remaining == messages[-2:]

    def test_count_accuracy(self):
        """Test that count() returns accurate count."""
        stm = ShortTermMemory(max_size=5)

        assert stm.count() == 0

        stm.add_message(LLMMessage(role="user", content="1"))
        assert stm.count() == 1

        stm.add_message(LLMMessage(role="user", content="2"))
        assert stm.count() == 2

        # Add more than capacity
        for i in range(10):
            stm.add_message(LLMMessage(role="user", content=f"Msg {i}"))

        assert stm.count() == 5  # Should cap at max_size


class TestShortTermMemoryClear:
    """Test clearing functionality."""

    def test_clear_empty_memory(self):
        """Test clearing empty memory."""
        stm = ShortTermMemory(max_size=5)

        messages = stm.clear()

        assert len(messages) == 0
        assert stm.count() == 0

    def test_clear_returns_messages(self):
        """Test that clear returns all messages."""
        stm = ShortTermMemory(max_size=5)

        msg1 = LLMMessage(role="user", content="First")
        msg2 = LLMMessage(role="assistant", content="Second")

        stm.add_message(msg1)
        stm.add_message(msg2)

        messages = stm.clear()

        assert len(messages) == 2
        assert messages == [msg1, msg2]

    def test_clear_empties_memory(self):
        """Test that clear empties the memory."""
        stm = ShortTermMemory(max_size=5)

        stm.add_message(LLMMessage(role="user", content="Message"))
        stm.clear()

        assert stm.count() == 0
        assert stm.get_messages() == []
        assert not stm.is_full()

    def test_clear_resets_full_status(self):
        """Test that clear resets full status."""
        stm = ShortTermMemory(max_size=2)

        stm.add_message(LLMMessage(role="user", content="1"))
        stm.add_message(LLMMessage(role="user", content="2"))

        assert stm.is_full()

        stm.clear()

        assert not stm.is_full()

    def test_add_after_clear(self):
        """Test adding messages after clearing."""
        stm = ShortTermMemory(max_size=3)

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

    def test_max_size_one(self):
        """Test with max_size of 1."""
        stm = ShortTermMemory(max_size=1)

        msg1 = LLMMessage(role="user", content="First")
        msg2 = LLMMessage(role="user", content="Second")

        stm.add_message(msg1)
        assert stm.count() == 1
        assert stm.is_full()

        stm.add_message(msg2)
        assert stm.count() == 1
        messages = stm.get_messages()
        assert messages == [msg2]  # Only second message

    def test_max_size_zero(self):
        """Test with max_size of 0 (degenerate case)."""
        stm = ShortTermMemory(max_size=0)

        stm.add_message(LLMMessage(role="user", content="Message"))

        # With maxlen=0, deque doesn't store anything
        assert stm.count() == 0

    def test_large_max_size(self):
        """Test with very large max_size."""
        stm = ShortTermMemory(max_size=10000)

        # Add many messages
        for i in range(100):
            stm.add_message(LLMMessage(role="user", content=f"Message {i}"))

        assert stm.count() == 100
        assert not stm.is_full()

    def test_message_with_complex_content(self):
        """Test adding messages with complex content."""
        stm = ShortTermMemory(max_size=5)

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
        stm = ShortTermMemory(max_size=5)

        stm.add_message(LLMMessage(role="user", content="Message"))

        stm.clear()
        stm.clear()
        stm.clear()

        assert stm.count() == 0


class TestShortTermMemoryBehavior:
    """Test specific behavioral scenarios."""

    def test_message_independence(self):
        """Test that stored messages are independent."""
        stm = ShortTermMemory(max_size=5)

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
        stm = ShortTermMemory(max_size=5)

        stm.add_message(LLMMessage(role="user", content="Message"))

        messages1 = stm.get_messages()
        messages2 = stm.get_messages()

        # Should be different list objects
        assert messages1 is not messages2
        # But contain same messages
        assert messages1 == messages2

    def test_eviction_doesnt_affect_cleared_messages(self):
        """Test that eviction doesn't affect previously cleared messages."""
        stm = ShortTermMemory(max_size=2)

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
        stm = ShortTermMemory(max_size=3)

        # Add, check, add, check, clear, add, check
        stm.add_message(LLMMessage(role="user", content="1"))
        assert stm.count() == 1

        stm.add_message(LLMMessage(role="user", content="2"))
        stm.add_message(LLMMessage(role="user", content="3"))
        assert stm.is_full()

        stm.add_message(LLMMessage(role="user", content="4"))
        messages = stm.get_messages()
        assert len(messages) == 3
        assert messages[0].content == "2"  # "1" was evicted

        stm.clear()
        assert stm.count() == 0

        stm.add_message(LLMMessage(role="user", content="5"))
        assert stm.count() == 1
