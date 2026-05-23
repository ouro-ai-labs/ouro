"""SQLite FTS5-backed recall index for conversation messages.

The index lives at ``<memory_dir>/recall.db`` and contains a single FTS5
virtual table with one row per message. Writes are best-effort: an indexing
failure must never break the loop. Reads are scoped by ``session_id`` when
provided.

Threading: ``sqlite3`` connections are not safe to share between threads, so
every operation opens a fresh connection inside ``asyncio.to_thread``. WAL
mode is enabled so concurrent readers/writers don't block each other.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from typing import Any, Iterable

from ouro.core.llm.message_types import LLMMessage

logger = logging.getLogger(__name__)

_DEFAULT_DB_NAME = "recall.db"


def _flatten_content(content: Any) -> str:
    """Flatten LLMMessage.content into a single searchable string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif "content" in block and isinstance(block["content"], str):
                    parts.append(block["content"])
        return "\n".join(p for p in parts if p)
    return str(content)


class RecallIndex:
    """FTS5-backed message store keyed by ``(session_id, message_idx)``.

    Use ``reindex_session`` to replace all rows for a session in one go —
    that's the natural fit for ``save_memory`` which writes the full
    snapshot. ``add_message`` is provided for incremental writes.
    """

    def __init__(self, memory_dir: str, db_name: str = _DEFAULT_DB_NAME) -> None:
        self.memory_dir = memory_dir
        self.db_path = os.path.join(memory_dir, db_name)

    # ---- sync helpers (run inside asyncio.to_thread) ---------------------

    def _connect(self) -> sqlite3.Connection:
        os.makedirs(self.memory_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        # FTS5 virtual table — content is searchable; the rest is UNINDEXED metadata.
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS messages USING fts5(
                session_id UNINDEXED,
                msg_idx UNINDEXED,
                role UNINDEXED,
                timestamp UNINDEXED,
                content
            )
            """
        )

    def _reindex_session_sync(
        self,
        session_id: str,
        messages: list[tuple[int, str, str, str]],
    ) -> None:
        """Replace all rows for session_id with the given messages.

        Args:
            session_id: Session UUID.
            messages: list of (msg_idx, role, timestamp, content).
        """
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            conn.execute("BEGIN")
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            if messages:
                conn.executemany(
                    "INSERT INTO messages (session_id, msg_idx, role, timestamp, content) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [(session_id, idx, role, ts, content) for idx, role, ts, content in messages],
                )
            conn.execute("COMMIT")
        finally:
            conn.close()

    def _add_message_sync(
        self,
        session_id: str,
        msg_idx: int,
        role: str,
        timestamp: str,
        content: str,
    ) -> None:
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            conn.execute(
                "INSERT INTO messages (session_id, msg_idx, role, timestamp, content) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, msg_idx, role, timestamp, content),
            )
        finally:
            conn.close()

    def _search_sync(
        self,
        query: str,
        session_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not os.path.isfile(self.db_path):
            return []
        conn = self._connect()
        try:
            cur = conn.cursor()
            # bm25() ranking — lower is more relevant
            if session_id:
                cur.execute(
                    "SELECT session_id, msg_idx, role, timestamp, content, bm25(messages) AS rank "
                    "FROM messages WHERE messages MATCH ? AND session_id = ? "
                    "ORDER BY rank LIMIT ?",
                    (query, session_id, limit),
                )
            else:
                cur.execute(
                    "SELECT session_id, msg_idx, role, timestamp, content, bm25(messages) AS rank "
                    "FROM messages WHERE messages MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (query, limit),
                )
            rows = cur.fetchall()
            return [
                {
                    "session_id": r[0],
                    "msg_idx": r[1],
                    "role": r[2],
                    "timestamp": r[3],
                    "content": r[4],
                    "score": r[5],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def _delete_session_sync(self, session_id: str) -> int:
        if not os.path.isfile(self.db_path):
            return 0
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            cur = conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            return cur.rowcount or 0
        finally:
            conn.close()

    # ---- async API -------------------------------------------------------

    async def reindex_session(
        self,
        session_id: str,
        messages: Iterable[LLMMessage],
        *,
        timestamp: str = "",
    ) -> None:
        """Atomically replace all FTS rows for *session_id* with *messages*.

        Empty-content messages are skipped (no point indexing tool-call
        scaffolding). Failures are logged but not raised — recall is
        non-critical.
        """
        rows: list[tuple[int, str, str, str]] = []
        for idx, msg in enumerate(messages):
            content = _flatten_content(msg.content)
            if not content.strip():
                continue
            rows.append((idx, msg.role, timestamp, content))
        try:
            await asyncio.to_thread(self._reindex_session_sync, session_id, rows)
        except Exception:
            logger.warning("FTS recall reindex failed for session %s", session_id, exc_info=True)

    async def add_message(
        self,
        session_id: str,
        msg_idx: int,
        message: LLMMessage,
        *,
        timestamp: str = "",
    ) -> None:
        content = _flatten_content(message.content)
        if not content.strip():
            return
        try:
            await asyncio.to_thread(
                self._add_message_sync,
                session_id,
                msg_idx,
                message.role,
                timestamp,
                content,
            )
        except Exception:
            logger.warning("FTS recall add_message failed", exc_info=True)

    async def search(
        self,
        query: str,
        *,
        session_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Run an FTS5 MATCH query, scoped to *session_id* if given.

        Returns at most *limit* hits ordered by bm25 relevance.
        """
        if not query or not query.strip():
            return []
        try:
            return await asyncio.to_thread(self._search_sync, query, session_id, limit)
        except sqlite3.OperationalError as e:
            # Common cause: malformed FTS query syntax. Surface a clean empty result.
            logger.debug("FTS recall search syntax error for query %r: %s", query, e)
            return []
        except Exception:
            logger.warning("FTS recall search failed", exc_info=True)
            return []

    async def delete_session(self, session_id: str) -> int:
        try:
            return await asyncio.to_thread(self._delete_session_sync, session_id)
        except Exception:
            logger.warning("FTS recall delete_session failed", exc_info=True)
            return 0
