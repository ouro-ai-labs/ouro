"""Conversation search tool — keyword search over historical messages.

Backed by the SQLite FTS5 ``RecallIndex``. Returns the most relevant past
messages for a query, optionally scoped to a single session.

This is the "recall memory" layer in the Letta/MemGPT sense: messages that
have been paged out of context can be searched on demand and pulled back
in as tool output.
"""

from __future__ import annotations

from typing import Any

from ouro.capabilities.memory.recall import RecallIndex
from ouro.core.runtime import get_memory_dir

from ..base import BaseTool

_DEFAULT_LIMIT = 5
_MAX_LIMIT = 20
_SNIPPET_LEN = 400


class ConversationSearchTool(BaseTool):
    """Search past conversation messages by keyword."""

    readonly = True

    def __init__(self, memory_dir: str | None = None) -> None:
        self._memory_dir = memory_dir or get_memory_dir()
        self._index = RecallIndex(self._memory_dir)

    @property
    def name(self) -> str:
        return "conversation_search"

    @property
    def description(self) -> str:
        return (
            "Search past conversation messages by keyword. Use this to recall "
            "what was said in earlier turns that are no longer in your context."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "query": {
                "type": "string",
                "description": "Keywords, double-quoted phrases, or AND/OR/NOT.",
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional session UUID to restrict the search. Omit to search "
                    "across all sessions."
                ),
                "default": "",
            },
            "limit": {
                "type": "integer",
                "description": f"Max results (default {_DEFAULT_LIMIT}, max {_MAX_LIMIT}).",
                "default": _DEFAULT_LIMIT,
            },
        }

    async def execute(
        self,
        query: str,
        session_id: str = "",
        limit: int = _DEFAULT_LIMIT,
    ) -> str:
        query = (query or "").strip()
        if not query:
            return "No query provided."

        try:
            limit_int = max(1, min(_MAX_LIMIT, int(limit)))
        except (TypeError, ValueError):
            limit_int = _DEFAULT_LIMIT

        results = await self._index.search(
            query,
            session_id=session_id or None,
            limit=limit_int,
        )
        if not results:
            return f"No matches for {query!r}."

        lines = [f"Found {len(results)} match(es) for {query!r}:\n"]
        for i, r in enumerate(results, 1):
            snippet = (r["content"] or "").strip().replace("\n", " ")
            if len(snippet) > _SNIPPET_LEN:
                snippet = snippet[:_SNIPPET_LEN] + "…"
            sid = r["session_id"][:8] if r.get("session_id") else "?"
            lines.append(
                f"[{i}] session={sid} role={r.get('role','?')} idx={r.get('msg_idx','?')}\n"
                f"    {snippet}"
            )
        return "\n".join(lines)
