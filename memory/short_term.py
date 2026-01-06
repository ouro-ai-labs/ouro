"""Short-term memory management with fixed-size window."""
from typing import List
from collections import deque


class ShortTermMemory:
    """Manages recent messages in a fixed-size sliding window."""

    def __init__(self, max_size: int = 20):
        """Initialize short-term memory.

        Args:
            max_size: Maximum number of messages to keep
        """
        self.max_size = max_size
        self.messages = deque(maxlen=max_size)

    def add_message(self, message: "LLMMessage") -> None:
        """Add a message to short-term memory.

        Automatically evicts oldest message if at capacity.

        Args:
            message: LLMMessage to add
        """
        self.messages.append(message)

    def get_messages(self) -> List["LLMMessage"]:
        """Get all messages in short-term memory.

        Returns:
            List of messages, oldest to newest
        """
        return list(self.messages)

    def get_recent(self, count: int) -> List["LLMMessage"]:
        """Get the N most recent messages.

        Args:
            count: Number of recent messages to retrieve

        Returns:
            List of recent messages, oldest to newest
        """
        if count >= len(self.messages):
            return list(self.messages)
        return list(self.messages)[-count:]

    def clear(self) -> List["LLMMessage"]:
        """Clear all messages and return them.

        Returns:
            List of all messages that were cleared
        """
        messages = list(self.messages)
        self.messages.clear()
        return messages

    def is_full(self) -> bool:
        """Check if short-term memory is at capacity.

        Returns:
            True if at max capacity
        """
        return len(self.messages) >= self.max_size

    def count(self) -> int:
        """Get current message count.

        Returns:
            Number of messages in short-term memory
        """
        return len(self.messages)

    def peek_oldest(self) -> "LLMMessage":
        """Peek at the oldest message without removing it.

        Returns:
            Oldest message, or None if empty
        """
        return self.messages[0] if self.messages else None

    def peek_newest(self) -> "LLMMessage":
        """Peek at the newest message without removing it.

        Returns:
            Newest message, or None if empty
        """
        return self.messages[-1] if self.messages else None
