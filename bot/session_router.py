"""Session router: maps IM conversations to agent instances."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from agent.agent import LoopAgent

logger = logging.getLogger(__name__)

# Default idle timeout: 1 hour
_DEFAULT_IDLE_TIMEOUT = 3600.0


class SessionRouter:
    """Routes IM conversations to per-conversation agent instances.

    Each conversation (keyed by "{channel}:{conversation_id}") gets its own
    LoopAgent with independent memory. A per-conversation lock serializes
    message processing since agent memory is not concurrent-safe.
    """

    def __init__(
        self,
        agent_factory: Callable[[], LoopAgent],
        idle_timeout: float = _DEFAULT_IDLE_TIMEOUT,
    ) -> None:
        """
        Args:
            agent_factory: Callable that returns a new LoopAgent instance.
            idle_timeout: Seconds of inactivity before a session is cleaned up.
        """
        self._agent_factory = agent_factory
        self._idle_timeout = idle_timeout
        self._sessions: dict[str, LoopAgent] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_active: dict[str, float] = {}

    def _session_key(self, channel: str, conversation_id: str) -> str:
        return f"{channel}:{conversation_id}"

    def get_or_create_agent(self, channel: str, conversation_id: str) -> LoopAgent:
        """Get an existing agent or create a new one for the conversation.

        Args:
            channel: Channel name (e.g. "feishu").
            conversation_id: IM conversation/chat ID.

        Returns:
            The LoopAgent for this conversation.
        """
        key = self._session_key(channel, conversation_id)
        if key not in self._sessions:
            logger.info("Creating new session for %s", key)
            self._sessions[key] = self._agent_factory()
            self._locks[key] = asyncio.Lock()
        self._last_active[key] = time.time()
        return self._sessions[key]

    def get_lock(self, channel: str, conversation_id: str) -> asyncio.Lock:
        """Get the per-conversation lock.

        Must be called after get_or_create_agent() to ensure the lock exists.

        Args:
            channel: Channel name.
            conversation_id: IM conversation/chat ID.

        Returns:
            asyncio.Lock for this conversation.
        """
        key = self._session_key(channel, conversation_id)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def cleanup_idle_sessions(self) -> int:
        """Remove sessions that have been idle longer than the timeout.

        Returns:
            Number of sessions removed.
        """
        now = time.time()
        expired_keys = [
            key
            for key, last_active in self._last_active.items()
            if now - last_active > self._idle_timeout
        ]

        for key in expired_keys:
            logger.info("Cleaning up idle session: %s", key)
            self._sessions.pop(key, None)
            self._locks.pop(key, None)
            self._last_active.pop(key, None)

        return len(expired_keys)

    def reset_session(self, channel: str, conversation_id: str) -> bool:
        """Destroy the session for a conversation. Returns True if a session existed."""
        key = self._session_key(channel, conversation_id)
        existed = key in self._sessions
        self._sessions.pop(key, None)
        self._locks.pop(key, None)
        self._last_active.pop(key, None)
        if existed:
            logger.info("Session reset for %s", key)
        return existed

    def get_session_age(self, channel: str, conversation_id: str) -> float | None:
        """Return seconds since the session was last active, or None if no session."""
        key = self._session_key(channel, conversation_id)
        ts = self._last_active.get(key)
        if ts is None:
            return None
        return time.time() - ts

    @property
    def active_session_count(self) -> int:
        """Number of active sessions."""
        return len(self._sessions)
