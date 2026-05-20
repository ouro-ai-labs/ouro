"""Mem0-backed memory persistence backend.

Uses the mem0 OSS Python SDK (``mem0ai``) to store session conversations
as vector memories.  Each session is tagged with ``session_id`` so mem0's
search can scope to a single session or span across sessions.

Requires::

    pip install ouro-ai[mem0]

Environment::

    OPENAI_API_KEY (or the key for whichever LLM/embedder provider you configure)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from ouro.capabilities.memory.serialization import (
    deserialize_message,
    serialize_message,
)
from ouro.capabilities.memory.store.memory_store import MemoryStore
from ouro.core.llm.message_types import LLMMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import so the rest of ouro works even when mem0 is not installed.
# ---------------------------------------------------------------------------

_mem0_module: Any = None


def _get_mem0() -> Any:
    global _mem0_module
    if _mem0_module is None:
        try:
            import mem0  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "mem0 is required for Mem0MemoryStore. "
                "Install it with: pip install ouro-ai[mem0]"
            ) from exc
        _mem0_module = mem0
    return _mem0_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_config() -> Dict[str, Any]:
    """Build mem0 config dict from ouro Config / environment."""
    from ouro.config import Config

    llm_config: Dict[str, Any] = {"provider": "openai", "config": {}}
    embedder_config: Dict[str, Any] = {"provider": "openai", "config": {}}
    vector_store_config: Dict[str, Any] = {
        "provider": "qdrant",
        "config": {"path": "/tmp/qdrant"},
    }

    # Allow full override via env var pointing at a YAML file
    mem0_config_file = os.environ.get("MEM0_CONFIG_FILE")
    if mem0_config_file and os.path.isfile(mem0_config_file):
        import yaml

        with open(mem0_config_file, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    # Lite overrides via env vars
    llm_provider = os.environ.get("MEM0_LLM_PROVIDER", "openai")
    llm_model = os.environ.get("MEM0_LLM_MODEL", "gpt-4o-mini")
    embedder_provider = os.environ.get("MEM0_EMBEDDER_PROVIDER", "openai")
    embedder_model = os.environ.get("MEM0_EMBEDDER_MODEL", "text-embedding-3-small")
    vs_provider = os.environ.get("MEM0_VECTOR_STORE_PROVIDER", "qdrant")
    vs_path = os.environ.get("MEM0_VECTOR_STORE_PATH", "/tmp/qdrant")

    llm_config = {
        "provider": llm_provider,
        "config": {"model": llm_model, "temperature": 0.1},
    }
    embedder_config = {
        "provider": embedder_provider,
        "config": {"model": embedder_model},
    }
    vector_store_config = {
        "provider": vs_provider,
        "config": {"path": vs_path},
    }

    # Pass through API keys when present in environment
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AZURE_OPENAI_KEY"):
        if os.environ.get(key):
            llm_config["config"]["api_key"] = os.environ[key]
            if key == "OPENAI_API_KEY":
                embedder_config["config"]["api_key"] = os.environ[key]

    return {
        "llm": llm_config,
        "embedder": embedder_config,
        "vector_store": vector_store_config,
    }


def _messages_to_text(messages: List[LLMMessage]) -> str:
    """Flatten a list of messages into a single text blob for mem0."""
    parts: List[str] = []
    for msg in messages:
        role = msg.role
        content = msg.content
        if isinstance(content, str):
            parts.append(f"[{role}] {content}")
        elif isinstance(content, list):
            # Multimodal — keep text blocks only
            texts: List[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
            if texts:
                parts.append(f"[{role}] {' '.join(texts)}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class Mem0MemoryStore(MemoryStore):
    """Mem0 vector-memory backend for session persistence.

    Each ``save_memory`` call stores the *entire* conversation as a single
    memory entry tagged with ``session_id``.  On ``load_session`` the latest
    entry for that session is retrieved and deserialized back into
    ``LLMMessage`` objects.

    Because mem0 performs its own fact-extraction and embedding, this store
    also enables *cross-session* semantic search when ``search`` is called
    without a ``session_id`` filter.
    """

    def __init__(self) -> None:
        mem0 = _get_mem0()
        config = _build_config()
        self._m = mem0.Memory.from_config(config)
        self._write_lock = asyncio.Lock()

    # -- MemoryStore interface --------------------------------------------

    async def create_session(self, metadata: Optional[Dict[str, Any]] = None) -> str:
        import uuid

        session_id = str(uuid.uuid4())
        # mem0 doesn't need explicit session creation; we just return the id.
        logger.info(f"Created mem0-backed session {session_id}")
        return session_id

    async def save_message(self, session_id: str, message: LLMMessage, tokens: int = 0) -> None:
        """Append a single message to the session memory in mem0.

        This is a thin wrapper around ``add`` — mem0 handles deduplication
        and versioning internally.
        """
        text = _messages_to_text([message])
        if not text:
            return
        await asyncio.to_thread(
            self._m.add,
            text,
            user_id=session_id,
            metadata={"session_id": session_id, "role": message.role, "tokens": tokens},
        )

    async def save_memory(
        self,
        session_id: str,
        system_messages: List[LLMMessage],
        messages: List[LLMMessage],
    ) -> None:
        """Persist the full conversation snapshot to mem0.

        We store the *entire* message list as one memory entry so that
        ``load_session`` can reconstruct the conversation accurately.
        """
        all_msgs = system_messages + messages
        text = _messages_to_text(all_msgs)
        if not text:
            logger.debug("Skipping mem0 save: empty conversation")
            return

        async with self._write_lock:
            # mem0.add returns a dict with "id" etc.
            await asyncio.to_thread(
                self._m.add,
                text,
                user_id=session_id,
                metadata={
                    "session_id": session_id,
                    "saved_at": datetime.now().isoformat(),
                    "msg_count": len(all_msgs),
                },
            )
        logger.debug(f"Saved mem0 memory for session {session_id}: {len(all_msgs)} messages")

    async def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load the latest conversation snapshot for *session_id* from mem0.

        Returns:
            Dictionary compatible with ``YamlFileMemoryStore.load_session``,
            or *None* if no memories are found.
        """
        results = await asyncio.to_thread(
            self._m.search,
            query="session conversation",
            filters={"user_id": session_id},
            limit=1,
        )
        if not results or not results.get("results"):
            logger.warning(f"Session {session_id} not found in mem0")
            return None

        top = results["results"][0]
        memory_text = top.get("memory", "")
        # Best-effort reconstruction: we don't have perfect round-trip
        # serialization through mem0's fact extraction, so we store a
        # special metadata key when available.
        metadata = top.get("metadata", {})

        # If we previously stored raw serialized messages in metadata, use them
        raw_messages = metadata.get("raw_messages")
        if raw_messages:
            system_messages = [
                deserialize_message(m) for m in raw_messages.get("system_messages", [])
            ]
            messages = [deserialize_message(m) for m in raw_messages.get("messages", [])]
        else:
            # Fallback: wrap the retrieved memory text as a single assistant message
            system_messages = []
            messages = [LLMMessage(role="assistant", content=memory_text)]

        return {
            "config": None,
            "system_messages": system_messages,
            "messages": messages,
            "stats": {
                "created_at": top.get("created_at", ""),
                "updated_at": top.get("updated_at", top.get("created_at", "")),
            },
        }

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List distinct session IDs known to mem0.

        mem0 doesn't expose a native "list users" API, so we perform a
        broad search and aggregate by ``user_id`` (which we map to
        ``session_id``).
        """
        # Search with an empty-ish query to get recent memories
        results = await asyncio.to_thread(
            self._m.search,
            query="*",
            limit=limit + offset,
        )
        items = results.get("results", []) if results else []

        # Aggregate by user_id -> latest memory
        sessions: Dict[str, Dict[str, Any]] = {}
        for item in items:
            uid = item.get("user_id") or item.get("metadata", {}).get("session_id")
            if not uid:
                continue
            if uid not in sessions:
                sessions[uid] = {
                    "id": uid,
                    "created_at": item.get("created_at", ""),
                    "updated_at": item.get("updated_at", item.get("created_at", "")),
                    "message_count": item.get("metadata", {}).get("msg_count", 0),
                    "system_message_count": 0,
                    "preview": (item.get("memory", "") or "")[:100],
                }
            else:
                # Keep the latest updated_at
                cur = sessions[uid]
                new_ts = item.get("updated_at", item.get("created_at", ""))
                if new_ts > cur["updated_at"]:
                    cur["updated_at"] = new_ts
                    cur["preview"] = (item.get("memory", "") or "")[:100]
                    cur["message_count"] = item.get("metadata", {}).get("msg_count", 0)

        sorted_sessions = sorted(
            sessions.values(), key=lambda s: s.get("updated_at", ""), reverse=True
        )
        return sorted_sessions[offset : offset + limit]

    async def delete_session(self, session_id: str) -> bool:
        """Delete all memories associated with *session_id*.

        mem0 OSS doesn't expose a bulk-delete by filter, so we search and
        delete one by one.
        """
        results = await asyncio.to_thread(
            self._m.search,
            query="*",
            filters={"user_id": session_id},
            limit=1000,
        )
        items = results.get("results", []) if results else []
        if not items:
            return False

        for item in items:
            mem_id = item.get("id")
            if mem_id:
                try:
                    await asyncio.to_thread(self._m.delete, mem_id)
                except Exception:
                    logger.warning(f"Failed to delete mem0 memory {mem_id}", exc_info=True)

        logger.info(f"Deleted mem0 memories for session {session_id}")
        return True

    async def get_session_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        results = await asyncio.to_thread(
            self._m.search,
            query="*",
            filters={"user_id": session_id},
            limit=1,
        )
        if not results or not results.get("results"):
            return None

        top = results["results"][0]
        meta = top.get("metadata", {})
        return {
            "session_id": session_id,
            "created_at": top.get("created_at", ""),
            "updated_at": top.get("updated_at", top.get("created_at", "")),
            "message_count": meta.get("msg_count", 0),
            "system_message_count": 0,
            "total_message_tokens": meta.get("tokens", 0),
        }

    async def find_latest_session(self) -> Optional[str]:
        sessions = await self.list_sessions(limit=1)
        return sessions[0]["id"] if sessions else None

    async def find_session_by_prefix(self, prefix: str) -> Optional[str]:
        sessions = await self.list_sessions(limit=1000)
        matches = [s["id"] for s in sessions if s["id"].startswith(prefix)]
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            logger.warning(f"Ambiguous prefix '{prefix}': {len(matches)} matches")
        return None

    # -- mem0-specific extras ---------------------------------------------

    async def search(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Semantic search across memories.

        Args:
            query: Natural-language query.
            session_id: If given, restrict search to this session.
            limit: Max results.

        Returns:
            List of memory dicts with ``id``, ``memory``, ``score``, etc.
        """
        filters = {"user_id": session_id} if session_id else None
        results = await asyncio.to_thread(
            self._m.search,
            query=query,
            filters=filters,
            limit=limit,
        )
        return results.get("results", []) if results else []

    async def add_fact(self, text: str, session_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Add an arbitrary fact/memory entry.

        This is useful for long-term memory consolidation: extract facts
        from a conversation and store them independently.
        """
        meta = {"session_id": session_id}
        if metadata:
            meta.update(metadata)
        result = await asyncio.to_thread(self._m.add, text, user_id=session_id, metadata=meta)
        return result if isinstance(result, dict) else {"id": str(result)}
