"""Short-term memory management with fixed-size window."""

from collections import deque
from typing import List

from llm.base import LLMMessage


class ShortTermMemory:
    """Manages recent messages in a fixed-size sliding window."""

    def __init__(self, max_size: int = 20):
        """Initialize short-term memory.

        Args:
            max_size: Maximum number of messages to keep
        """
        self.max_size = max_size
        self.messages = deque(maxlen=max_size)

    def add_message(self, message: LLMMessage) -> None:
        """Add a message to short-term memory.

        Automatically evicts oldest message if at capacity.

        Args:
            message: LLMMessage to add
        """
        self.messages.append(message)

    def get_messages(self) -> List[LLMMessage]:
        """Get all messages in short-term memory.

        Returns:
            List of messages, oldest to newest
        """
        return list(self.messages)

    def clear(self) -> List[LLMMessage]:
        """Clear all messages and return them.

        Returns:
            List of all messages that were cleared
        """
        messages = list(self.messages)
        self.messages.clear()
        return messages

    def remove_first(self, count: int) -> List[LLMMessage]:
        """Remove the first N messages (oldest) from memory.

        This is useful after compression to remove only the compressed messages
        while preserving any new messages that arrived during compression.

        Args:
            count: Number of messages to remove from the front

        Returns:
            List of removed messages
        """
        return [self.messages.popleft() for _ in range(min(count, len(self.messages)))]

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
