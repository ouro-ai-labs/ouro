"""Session router: maps IM conversations to agent instances."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import aiofiles
import yaml

from agent.agent import LoopAgent

logger = logging.getLogger(__name__)

_CONVERSATION_MAP_FILE = "conversation_map.yaml"

# Default threshold for disk-level session cleanup (days)
_DEFAULT_STALE_DAYS = 30


class SessionRouter:
    """Routes IM conversations to per-conversation agent instances.

    Each conversation (keyed by "{channel}:{conversation_id}") gets its own
    LoopAgent with independent memory. Serialization is handled externally
    by the message queue (one consumer task per conversation).

    When ``sessions_dir`` is provided, the router persists a conversation map
    (conversation key -> session UUID) so sessions survive bot restarts.
    """

    def __init__(
        self,
        agent_factory: Callable[[], LoopAgent] | Callable[[], Awaitable[LoopAgent]],
        sessions_dir: str | None = None,
    ) -> None:
        """
        Args:
            agent_factory: Callable that returns a (possibly awaitable) LoopAgent.
            sessions_dir: Optional directory for session persistence and conversation map.
        """
        self._agent_factory = agent_factory
        self._sessions_dir = sessions_dir
        self._sessions: dict[str, LoopAgent] = {}
        self._last_active: dict[str, float] = {}

        # Persistent conversation map: conv_key -> session UUID
        self._conversation_map: dict[str, str] = {}

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
            await self._save_conversation_map()

    async def cleanup_stale_sessions(self, max_age_days: int = _DEFAULT_STALE_DAYS) -> int:
        """Delete persisted sessions that haven't been updated in *max_age_days*.

        Also removes the corresponding conversation map entries.

        Returns:
            Number of sessions deleted from disk.
        """
        if not self._sessions_dir:
            return 0

        from memory.store import YamlFileMemoryStore

        store = YamlFileMemoryStore(sessions_dir=self._sessions_dir)
        sessions = await store.list_sessions(limit=1000)

        cutoff = datetime.now() - timedelta(days=max_age_days)
        deleted = 0
        map_changed = False

        for s in sessions:
            updated_str = s.get("updated_at", "")
            if not updated_str:
                continue
            try:
                updated_at = datetime.fromisoformat(updated_str)
            except (ValueError, TypeError):
                continue
            if updated_at >= cutoff:
                continue

            session_id = s["id"]
            if await store.delete_session(session_id):
                deleted += 1
                logger.info(
                    "Deleted stale session %s (updated %s)", session_id[:8], updated_str[:10]
                )

            # Remove any conversation map entries pointing to this session
            stale_keys = [k for k, v in self._conversation_map.items() if v == session_id]
            for k in stale_keys:
                del self._conversation_map[k]
                map_changed = True

        if map_changed:
            await self._save_conversation_map()

        return deleted

    async def reset_session(self, channel: str, conversation_id: str) -> bool:
        """Destroy the session for a conversation. Returns True if a session existed."""
        key = self._session_key(channel, conversation_id)
        existed = key in self._sessions
        self._sessions.pop(key, None)
        self._last_active.pop(key, None)
        if key in self._conversation_map:
            del self._conversation_map[key]
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

    async def save_session(self, channel: str, conversation_id: str) -> None:
        """Save the current agent's memory to disk (no-op if no session exists)."""
        key = self._session_key(channel, conversation_id)
        agent = self._sessions.get(key)
        if agent:
            await agent.memory.save_memory()

    async def list_persisted_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """List persisted sessions from disk.

        Args:
            limit: Maximum number of sessions to return.

        Returns:
            List of session summaries from the store.
        """
        from memory.manager import MemoryManager

        return await MemoryManager.list_sessions(limit=limit, sessions_dir=self._sessions_dir)

    async def find_session_by_prefix(self, prefix: str) -> str | None:
        """Find a persisted session by ID prefix.

        Args:
            prefix: Prefix of session UUID.

        Returns:
            Full session ID, or None if not found.
        """
        from memory.manager import MemoryManager

        return await MemoryManager.find_session_by_prefix(prefix, sessions_dir=self._sessions_dir)

    def get_last_active_session(self) -> tuple[str, str] | None:
        """Return (channel_name, conversation_id) for the most recently active session."""
        if not self._last_active:
            return None
        best_key = max(self._last_active, key=self._last_active.get)  # type: ignore[arg-type]
        channel, conversation_id = best_key.split(":", 1)
        return (channel, conversation_id)

    @property
    def active_session_count(self) -> int:
        """Number of active sessions."""
        return len(self._sessions)
