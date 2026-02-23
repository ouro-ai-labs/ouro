"""Session router: maps IM conversations to agent instances."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aiofiles
import yaml

from agent.agent import LoopAgent

logger = logging.getLogger(__name__)

# Default idle timeout: 1 hour
_DEFAULT_IDLE_TIMEOUT = 3600.0

_CONVERSATION_MAP_FILE = "conversation_map.yaml"


class SessionRouter:
    """Routes IM conversations to per-conversation agent instances.

    Each conversation (keyed by "{channel}:{conversation_id}") gets its own
    LoopAgent with independent memory. A per-conversation lock serializes
    message processing since agent memory is not concurrent-safe.

    When ``sessions_dir`` is provided, the router persists a conversation map
    (conversation key -> session UUID) so sessions survive bot restarts.
    """

    def __init__(
        self,
        agent_factory: Callable[[], LoopAgent] | Callable[[], Awaitable[LoopAgent]],
        idle_timeout: float = _DEFAULT_IDLE_TIMEOUT,
        sessions_dir: str | None = None,
    ) -> None:
        """
        Args:
            agent_factory: Callable that returns a (possibly awaitable) LoopAgent.
            idle_timeout: Seconds of inactivity before a session is cleaned up.
            sessions_dir: Optional directory for session persistence and conversation map.
        """
        self._agent_factory = agent_factory
        self._idle_timeout = idle_timeout
        self._sessions_dir = sessions_dir
        self._sessions: dict[str, LoopAgent] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_active: dict[str, float] = {}

        # Persistent conversation map: conv_key -> session UUID
        self._conversation_map: dict[str, str] = {}
        self._map_dirty = False

    def _session_key(self, channel: str, conversation_id: str) -> str:
        return f"{channel}:{conversation_id}"

    # ---- Conversation map persistence ----------------------------------------

    def _conversation_map_path(self) -> str | None:
        if not self._sessions_dir:
            return None
        return os.path.join(self._sessions_dir, _CONVERSATION_MAP_FILE)

    async def load_conversation_map(self) -> None:
        """Load the conversation map from disk (call once at startup)."""
        path = self._conversation_map_path()
        if not path or not os.path.exists(path):
            return
        try:
            async with aiofiles.open(path, encoding="utf-8") as f:
                content = await f.read()
            data = yaml.safe_load(content)
            if isinstance(data, dict):
                self._conversation_map = data
                logger.info("Loaded conversation map: %d entries", len(data))
        except Exception:
            logger.warning("Failed to load conversation map", exc_info=True)

    async def _save_conversation_map(self) -> None:
        """Atomically write the conversation map to disk."""
        path = self._conversation_map_path()
        if not path:
            return
        tmp_path = path + ".tmp"
        content = yaml.dump(
            self._conversation_map,
            default_flow_style=False,
            allow_unicode=True,
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(content)
        await asyncio.to_thread(os.replace, tmp_path, path)
        self._map_dirty = False

    async def flush_map(self) -> None:
        """Save the conversation map if it has been modified."""
        if self._map_dirty:
            await self._save_conversation_map()

    # ---- Session lifecycle ---------------------------------------------------

    async def get_or_create_agent(self, channel: str, conversation_id: str) -> LoopAgent:
        """Get an existing agent or create a new one for the conversation.

        If a persisted session exists in the conversation map, loads it
        into the new agent automatically.

        Args:
            channel: Channel name (e.g. "feishu").
            conversation_id: IM conversation/chat ID.

        Returns:
            The LoopAgent for this conversation.
        """
        key = self._session_key(channel, conversation_id)
        if key not in self._sessions:
            logger.info("Creating new session for %s", key)
            agent_or_coro = self._agent_factory()
            if asyncio.isfuture(agent_or_coro) or asyncio.iscoroutine(agent_or_coro):
                agent_or_coro = await agent_or_coro
            result: LoopAgent = agent_or_coro  # type: ignore[assignment]

            # Try to resume from persisted session
            saved_session_id = self._conversation_map.get(key)
            if saved_session_id:
                try:
                    await result.load_session(saved_session_id)
                    logger.info("Resumed session %s for %s", saved_session_id[:8], key)
                except Exception:
                    logger.warning(
                        "Failed to resume session %s for %s, starting fresh",
                        saved_session_id[:8],
                        key,
                        exc_info=True,
                    )

            self._sessions[key] = result
            self._locks[key] = asyncio.Lock()
        self._last_active[key] = time.time()
        return self._sessions[key]

    async def update_session_mapping(self, channel: str, conversation_id: str) -> None:
        """Persist the current agent's session ID in the conversation map.

        Call after agent.run() to keep the map up to date.
        """
        key = self._session_key(channel, conversation_id)
        agent = self._sessions.get(key)
        if not agent or not agent.memory.session_id:
            return
        old = self._conversation_map.get(key)
        if old != agent.memory.session_id:
            self._conversation_map[key] = agent.memory.session_id
            self._map_dirty = True
            await self._save_conversation_map()

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
        """Remove in-memory sessions that have been idle longer than the timeout.

        Conversation map entries are *kept* so sessions can resume after cleanup.

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
            # Keep self._conversation_map[key] so next message resumes the session

        return len(expired_keys)

    async def reset_session(self, channel: str, conversation_id: str) -> bool:
        """Destroy the session for a conversation. Returns True if a session existed."""
        key = self._session_key(channel, conversation_id)
        existed = key in self._sessions
        self._sessions.pop(key, None)
        self._locks.pop(key, None)
        self._last_active.pop(key, None)
        if key in self._conversation_map:
            del self._conversation_map[key]
            self._map_dirty = True
            await self._save_conversation_map()
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

    def iter_active_sessions(self) -> list[tuple[str, str]]:
        """Return (channel_name, conversation_id) pairs for all live sessions."""
        result: list[tuple[str, str]] = []
        for key in self._sessions:
            channel, conversation_id = key.split(":", 1)
            result.append((channel, conversation_id))
        return result

    def is_session_busy(self, channel: str, conversation_id: str) -> bool:
        """Check whether the session lock is currently held (agent processing)."""
        key = self._session_key(channel, conversation_id)
        lock = self._locks.get(key)
        if lock is None:
            return False
        return lock.locked()

    async def list_persisted_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """List persisted sessions from disk.

        Args:
            limit: Maximum number of sessions to return.

        Returns:
            List of session summaries from the store.
        """
        from memory.manager import MemoryManager

        return await MemoryManager.list_sessions(limit=limit, sessions_dir=self._sessions_dir)

    @property
    def active_session_count(self) -> int:
        """Number of active sessions."""
        return len(self._sessions)
