"""SessionPersistenceHook — incremental session persistence on every message.

Wires MemoryManager into the core loop so that each new message is
appended to session.yaml immediately, rather than waiting until the
entire turn finishes.  This gives crash-safety for long multi-tool
runs and for long-lived bot processes.
"""

from __future__ import annotations

from typing import Any

from ouro.core.log import get_logger
from ouro.core.loop.message_list import MessageList
from ouro.core.loop.protocols import ContinueDecision, LoopContext

from .manager import MemoryManager

logger = get_logger(__name__)


class SessionPersistenceHook:
    """Incrementally persist conversation messages to disk.

    Structurally satisfies the ``core.loop.Hook`` Protocol via
    ``on_run_start`` and ``on_iteration_end``.  We deliberately *don't*
    inherit from ``Hook``: Protocol method bodies are ``...`` which at
    runtime resolves to ``return None``.  Inheriting would supply no-op
    stubs for every lifecycle method.
    """

    def __init__(self, memory: MemoryManager) -> None:
        self.memory = memory
        self._last_saved_count: int = 0

    async def on_run_start(self, ctx: LoopContext, messages: MessageList) -> None:
        """Reset incremental counter at the start of every run."""
        self._last_saved_count = 0

    async def on_iteration_end(
        self,
        ctx: LoopContext,
        messages: MessageList,
        response: Any,
        finished: bool,
    ) -> ContinueDecision:
        """Persist any messages that have been appended since last save.

        This runs after every iteration (both TOOL_CALLS and STOP),
        ensuring that assistant messages and tool results are flushed
        to disk before the next LLM call.
        """
        if self.memory.session_id is None:
            return ContinueDecision.cont()

        current_count = len(messages.snapshot())
        if current_count <= self._last_saved_count:
            return ContinueDecision.cont()

        new_messages = messages.snapshot()[self._last_saved_count :]
        for msg in new_messages:
            try:
                await self.memory.save_single_message(msg)
            except Exception:  # noqa: PERF203
                # Best-effort: each message is independent; one failure
                # must not prevent the rest from persisting.
                logger.warning(
                    "Failed to incrementally save message for session %s",
                    self.memory.session_id,
                    exc_info=True,
                )

        self._last_saved_count = current_count
        logger.debug(
            "Incrementally saved %d message(s) for session %s",
            len(new_messages),
            self.memory.session_id,
        )
        return ContinueDecision.cont()
