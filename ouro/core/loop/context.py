"""Loop execution context.

`RunStatistic` holds mutable per-run state (iterations, token usage).
`MessageListContext` is the long-lived container for the conversation
state of a session: system messages + a mutable `MessageList` for the
detached/conversation messages. The core loop uses it as the canonical
source of truth so memory layer no longer needs to own messages.

Design note: ``MessageListContext`` deliberately does *not* re-export
the mutation API of its inner ``MessageList``.  Callers that need to
push or read conversation messages do so via ``ctx.detached`` directly
(``ctx.detached.append(...)``, ``ctx.detached.snapshot()``).  Only the
system-message side and the combined ``build_context()`` view live on
the context itself.
"""

from __future__ import annotations

from typing import Callable, Iterable

from ouro.core.llm import LLMMessage
from ouro.core.loop.message_list import MessageList
from ouro.core.loop.protocols import ProgressSink


class RunStatistic:
    """Mutable run state. Exposed to hooks via the LoopContext Protocol view."""

    def __init__(
        self,
        task: str,
        progress: ProgressSink,
        *,
        usage_callback: Callable[[dict[str, int]], None] | None = None,
    ) -> None:
        self.task = task
        self.iteration = 0
        self.usage_total: dict[str, int] = {}
        self.stop_reason_last: str | None = None
        self.progress = progress
        self._usage_callback = usage_callback

    def add_usage(self, usage: dict[str, int] | None) -> None:
        if not usage:
            return
        for k, v in usage.items():
            if isinstance(v, int):
                self.usage_total[k] = self.usage_total.get(k, 0) + v
        if self._usage_callback is not None:
            self._usage_callback(usage)


class MessageListContext:
    """Owns system messages + the detached conversation MessageList.

    The detached list is the *loop-level* mutable history that hooks
    read and write through the standard Hook protocol (which receives a
    plain ``MessageList``).  System messages live alongside as a plain
    list because they're fixed early and the LLM consumes them as a
    prefix of every call.

    Capability code (``ComposedAgent``, ``CompactionHook``, …) reads
    and writes via ``ctx.detached`` directly; this class only owns the
    system-side and the flat ``build_context()`` projection.
    """

    def __init__(
        self,
        *,
        system_messages: Iterable[LLMMessage] | None = None,
        detached: MessageList | Iterable[LLMMessage] | None = None,
    ) -> None:
        self.system_messages: list[LLMMessage] = list(system_messages or [])
        if isinstance(detached, MessageList):
            self.detached = detached
        else:
            self.detached = MessageList(detached or [])

    # -- system messages ---------------------------------------------------

    def add_system_message(self, message: LLMMessage) -> None:
        """Append a system message."""
        self.system_messages.append(message)

    def set_system_messages(self, messages: Iterable[LLMMessage]) -> None:
        """Replace the entire system message list."""
        self.system_messages = list(messages)

    def clear_system_messages(self) -> None:
        """Remove all system messages."""
        self.system_messages.clear()

    @property
    def has_system_messages(self) -> bool:
        return bool(self.system_messages)

    # -- combined context --------------------------------------------------

    def build_context(self) -> list[LLMMessage]:
        """Return system messages + detached messages as a flat list.

        This is what the LLM consumes for each call.
        """
        return list(self.system_messages) + self.detached.snapshot()
