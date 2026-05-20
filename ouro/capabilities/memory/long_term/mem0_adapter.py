"""Mem0-backed long-term memory adapter.

Replaces (or supplements) the file-based ``LongTermMemoryManager`` with
mem0's vector search.  Instead of reading ``memory.md`` and daily files,
this adapter:

1. **Searches** mem0 for relevant memories at session start.
2. **Adds** new facts extracted from conversations at session end.
3. **Supports cross-session recall** — memories from previous sessions
   surface automatically via semantic search.

Requires::

    pip install ouro-ai[mem0]
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from ouro.config import Config

if TYPE_CHECKING:
    from ouro.core.llm import LiteLLMAdapter

logger = logging.getLogger(__name__)

# Import base class at module level to satisfy linters and avoid E402.
# The circular import is safe because BaseLongTermMemory is defined in
# ``__init__.py`` before this module is imported.
from ouro.capabilities.memory.long_term import BaseLongTermMemory  # noqa: E402

# ---------------------------------------------------------------------------
# Lazy import
# ---------------------------------------------------------------------------

_mem0_module: Any = None


def _get_mem0() -> Any:
    global _mem0_module
    if _mem0_module is None:
        try:
            import mem0  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "mem0 is required for Mem0LongTermMemory. "
                "Install it with: pip install ouro-ai[mem0]"
            ) from exc
        _mem0_module = mem0
    return _mem0_module


# ---------------------------------------------------------------------------
# Config builder (shared with mem0_memory_store)
# ---------------------------------------------------------------------------


def _build_mem0_config() -> dict[str, Any]:
    """Build mem0 config dict from environment."""
    import os

    mem0_config_file = os.environ.get("MEM0_CONFIG_FILE")
    if mem0_config_file and os.path.isfile(mem0_config_file):
        import yaml

        with open(mem0_config_file, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    llm_provider = os.environ.get("MEM0_LLM_PROVIDER", "openai")
    llm_model = os.environ.get("MEM0_LLM_MODEL", "gpt-4o-mini")
    embedder_provider = os.environ.get("MEM0_EMBEDDER_PROVIDER", "openai")
    embedder_model = os.environ.get("MEM0_EMBEDDER_MODEL", "text-embedding-3-small")
    vs_provider = os.environ.get("MEM0_VECTOR_STORE_PROVIDER", "qdrant")
    vs_path = os.environ.get("MEM0_VECTOR_STORE_PATH", "/tmp/qdrant")

    llm_config: dict[str, Any] = {
        "provider": llm_provider,
        "config": {"model": llm_model, "temperature": 0.1},
    }
    embedder_config: dict[str, Any] = {
        "provider": embedder_provider,
        "config": {"model": embedder_model},
    }
    vector_store_config: dict[str, Any] = {
        "provider": vs_provider,
        "config": {"path": vs_path},
    }

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


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_INSTRUCTION_TEMPLATE = """\
<long_term_memory>
You have a persistent long-term memory system powered by mem0.

Relevant memories from previous sessions:
{memories}

When you learn something durable (preferences, decisions, project facts,
environment details), it is automatically stored for future sessions.
</long_term_memory>"""


class Mem0LongTermMemory(BaseLongTermMemory):
    """Long-term memory facade backed by mem0 vector search.

    This is a drop-in replacement for ``LongTermMemoryManager`` in
    ``MemoryManager``.  It uses mem0's ``search`` to surface relevant
    past memories and ``add`` to persist new facts.
    """

    def __init__(self, llm: LiteLLMAdapter, user_id: str | None = None) -> None:
        self.llm = llm
        self.user_id = user_id or "default_user"
        mem0 = _get_mem0()
        config = _build_mem0_config()
        self._m = mem0.Memory.from_config(config)

    # ------------------------------------------------------------------
    # Public API (mirrors LongTermMemoryManager)
    # ------------------------------------------------------------------

    async def load_and_format(self) -> str | None:
        """Search mem0 for recent / relevant memories and format them.

        Returns:
            A ``<long_term_memory>`` XML block, or *None* if no memories.
        """
        try:
            memories = await self._fetch_memories()
        except Exception:
            logger.warning("Failed to fetch mem0 memories", exc_info=True)
            return None

        if not memories:
            return None

        formatted = self._format_memories(memories)
        return _INSTRUCTION_TEMPLATE.format(memories=formatted)

    async def add_memories_from_conversation(
        self,
        messages: list[Any],
        session_id: str,
    ) -> None:
        """Extract and store durable facts from a conversation.

        This should be called at the end of a session (or after a
        compaction) to promote condensed knowledge into long-term memory.

        Args:
            messages: Conversation messages (list of LLMMessage-like objects).
            session_id: The current session identifier.
        """
        text = self._messages_to_text(messages)
        if not text:
            return

        # mem0.add automatically extracts facts and embeddings.
        try:
            await asyncio.to_thread(
                self._m.add,
                text,
                user_id=self.user_id,
                metadata={
                    "session_id": session_id,
                    "source": "conversation",
                    "date": date.today().isoformat(),
                },
            )
            logger.info("Stored conversation memories in mem0")
        except Exception:
            logger.warning("Failed to add memories to mem0", exc_info=True)

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Semantic search across long-term memories.

        Args:
            query: Natural-language query.
            limit: Max results.

        Returns:
            List of memory dicts.
        """
        try:
            results = await asyncio.to_thread(
                self._m.search,
                query=query,
                filters={"user_id": self.user_id},
                limit=limit,
            )
            return results.get("results", []) if results else []
        except Exception:
            logger.warning("mem0 search failed", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _fetch_memories(self) -> list[dict[str, Any]]:
        """Fetch the most recent / relevant memories for the user."""
        # Strategy: search with a broad query to get recent memories.
        # mem0 returns results ordered by relevance; we also sort by date.
        results = await asyncio.to_thread(
            self._m.search,
            query="recent activities preferences decisions",
            filters={"user_id": self.user_id},
            limit=Config.LONG_TERM_MEMORY_DAILY_WINDOW * 3,
        )
        items = results.get("results", []) if results else []
        # Sort by created_at descending (most recent first)
        items.sort(
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )
        return items

    @staticmethod
    def _format_memories(memories: list[dict[str, Any]]) -> str:
        """Format mem0 results into a readable markdown list."""
        if not memories:
            return "(no memories yet)"
        lines = []
        for mem in memories:
            mem_text = mem.get("memory", "")
            if not mem_text:
                continue
            created = mem.get("created_at", "")
            lines.append(f"- {mem_text}  ({created})")
        return "\n".join(lines) if lines else "(no memories yet)"

    @staticmethod
    def _messages_to_text(messages: list[Any]) -> str:
        """Flatten messages to a text blob for mem0 ingestion."""
        parts: list[str] = []
        for msg in messages:
            role = getattr(msg, "role", "unknown")
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                parts.append(f"[{role}] {content}")
            elif isinstance(content, list):
                texts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                if texts:
                    parts.append(f"[{role}] {' '.join(texts)}")
        return "\n".join(parts)
