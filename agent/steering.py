"""Steering queues for mid-task user message injection.

Two non-blocking queues let callers (TUI, bot channels) inject messages while
an agent is executing a task:

- ``steering``: delivered at the next safe checkpoint within the current run
  (between LLM turns, or between tools in a sequential batch). Drained in
  ``all`` mode — the full queue is consumed at each checkpoint, in arrival
  order, and appended to memory as regular ``role: user`` messages.
- ``follow_up``: delivered *after* the current run completes. Drained by the
  caller (e.g., :class:`InteractiveSession`, bot session router) which then
  triggers a new ``agent.run()`` with the combined text.

Both queues cap at :data:`DEFAULT_QUEUE_CAP` messages; overflow drops the
oldest entry with a warning log.

See ``rfc/016-agent-steering.md`` for the design.
"""

from __future__ import annotations

from collections import deque

from utils import get_logger

logger = get_logger(__name__)

DEFAULT_QUEUE_CAP = 32


class SteeringQueues:
    """Non-blocking message queues for mid-task user input.

    All methods are safe to call from any coroutine on the agent's event loop.
    Enqueue methods (:meth:`steer`, :meth:`follow_up`) are synchronous and
    never block — they append to an in-memory deque.
    """

    def __init__(self, cap: int = DEFAULT_QUEUE_CAP) -> None:
        self._steering: deque[str] = deque()
        self._follow_up: deque[str] = deque()
        self._is_running = False
        self._cap = cap

    # ------------------------------------------------------------------ #
    # Enqueue
    # ------------------------------------------------------------------ #

    def steer(self, text: str) -> None:
        """Queue a steering message for the next checkpoint.

        Whitespace-only text is ignored. When the queue is full, the oldest
        entry is dropped with a warning log.
        """
        self._enqueue(self._steering, text, label="steering")

    def follow_up(self, text: str) -> None:
        """Queue a follow-up message to fire after the current run ends.

        Whitespace-only text is ignored. When the queue is full, the oldest
        entry is dropped with a warning log.
        """
        self._enqueue(self._follow_up, text, label="follow-up")

    def _enqueue(self, q: deque[str], text: str, *, label: str) -> None:
        text = text.strip()
        if not text:
            return
        if len(q) >= self._cap:
            dropped = q.popleft()
            logger.warning(
                "%s queue full (cap=%d); dropped oldest: %r",
                label,
                self._cap,
                dropped[:80],
            )
        q.append(text)

    # ------------------------------------------------------------------ #
    # Drain (``all`` mode — empty the queue in one call)
    # ------------------------------------------------------------------ #

    def drain_steering(self) -> list[str]:
        """Return all pending steering messages in arrival order."""
        if not self._steering:
            return []
        drained = list(self._steering)
        self._steering.clear()
        return drained

    def drain_follow_up(self) -> list[str]:
        """Return all pending follow-up messages in arrival order."""
        if not self._follow_up:
            return []
        drained = list(self._follow_up)
        self._follow_up.clear()
        return drained

    # ------------------------------------------------------------------ #
    # Introspection (used by checkpoints + /steering status)
    # ------------------------------------------------------------------ #

    def is_running(self) -> bool:
        """Whether the agent is currently inside an ``agent.run()`` call."""
        return self._is_running

    def pending_steering(self) -> int:
        return len(self._steering)

    def pending_follow_up(self) -> int:
        return len(self._follow_up)

    def pending_counts(self) -> tuple[int, int]:
        return len(self._steering), len(self._follow_up)

    def snapshot(self) -> dict:
        """Copy of queue state for display (``/steering status``)."""
        return {
            "is_running": self._is_running,
            "steering": list(self._steering),
            "follow_up": list(self._follow_up),
        }

    # ------------------------------------------------------------------ #
    # Run-state (flipped by BaseAgent around ``run()``)
    # ------------------------------------------------------------------ #

    def _mark_running(self) -> None:
        self._is_running = True

    def _mark_idle(self) -> None:
        self._is_running = False
