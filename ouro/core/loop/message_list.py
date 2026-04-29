"""Message list abstraction for the core loop.

`MessageList` centralizes mutable conversation history operations so the loop
can stop depending on a raw `list[LLMMessage]` everywhere. Hooks mutate and
observe this loop-owned state directly, while LLM calls consume snapshots.
"""

from __future__ import annotations

from typing import Iterable, Iterator

from ouro.core.llm import LLMMessage


class MessageList:
    """Mutable wrapper around a conversation message list."""

    def __init__(self, messages: Iterable[LLMMessage] | None = None) -> None:
        self._messages: list[LLMMessage] = list(messages or [])

    def __iter__(self) -> Iterator[LLMMessage]:
        return iter(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def __getitem__(self, index: int) -> LLMMessage:
        return self._messages[index]

    def snapshot(self) -> list[LLMMessage]:
        """Return a shallow copy of current messages."""
        return list(self._messages)

    def replace(self, messages: Iterable[LLMMessage]) -> list[LLMMessage]:
        """Replace stored messages and return a fresh snapshot."""
        self._messages = list(messages)
        return self.snapshot()

    def replace_range(
        self,
        start: int,
        end: int,
        new_items: Iterable[LLMMessage],
    ) -> list[LLMMessage]:
        """Replace a slice and return a fresh snapshot."""
        items = list(new_items)
        self._messages[start:end] = items
        return self.snapshot()

    def clear(self) -> None:
        self._messages.clear()

    def append(self, message: LLMMessage) -> None:
        self._messages.append(message)

    def extend(self, messages: Iterable[LLMMessage]) -> None:
        self._messages.extend(messages)
