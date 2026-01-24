"""Persistent storage for memory using embedded SQLite database."""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiofiles.os
import aiosqlite

from llm.message_types import LLMMessage
from memory.types import CompressedMemory

logger = logging.getLogger(__name__)


class MemoryStore:
    """Simplified persistent storage for conversation memory using SQLite.

    Features:
    - Single table structure for easy management
    - Store complete conversation history by session
    - Save/load memory state (messages + summaries)
    - Query historical sessions
    """

    def __init__(self, db_path: str = "data/memory.db"):
        """Initialize memory store.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._db_initialized = False
        self._init_lock = asyncio.Lock()

        logger.info(f"MemoryStore initialized at {db_path}")

    async def _ensure_db(self) -> None:
        if self._db_initialized:
            return
        async with self._init_lock:
            if self._db_initialized:
                return
            await aiofiles.os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            await self._init_db()
            self._db_initialized = True

    async def _init_db(self) -> None:
        """Initialize database schema with single table."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    messages TEXT,
                    system_messages TEXT,
                    summaries TEXT
                )
            """
            )
            await conn.commit()
            logger.debug("Database schema initialized")

    async def create_session(self, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Create a new session.

        Args:
            metadata: Optional session metadata (description, tags, etc.)

        Returns:
            Session ID (UUID)
        """
        await self._ensure_db()
        session_id = str(uuid.uuid4())
        # Store as ISO 8601 text to avoid sqlite3's deprecated default datetime adapter (Python 3.12+).
        now = datetime.now().isoformat()

        # Initialize with empty lists
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO sessions (id, created_at, messages, system_messages, summaries)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    now,
                    json.dumps([]),  # Empty messages list
                    json.dumps([]),  # Empty system_messages list
                    json.dumps([]),  # Empty summaries list
                ),
            )
            await conn.commit()

        logger.info(f"Created session {session_id}")
        return session_id

    async def save_message(self, session_id: str, message: LLMMessage, tokens: int = 0):
        """Save a message to the database.

        Args:
            session_id: Session ID
            message: LLMMessage to save
            tokens: Token count for this message
        """
        await self._ensure_db()
        async with aiosqlite.connect(self.db_path) as conn:
            field = "system_messages" if message.role == "system" else "messages"

            async with conn.execute(
                f"SELECT {field} FROM sessions WHERE id = ?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    logger.warning(f"Session {session_id} not found")
                    return

            messages = json.loads(row[0]) if row[0] else []
            msg_data = self._serialize_message(message)
            msg_data["tokens"] = tokens
            messages.append(msg_data)

            await conn.execute(
                f"UPDATE sessions SET {field} = ? WHERE id = ?", (json.dumps(messages), session_id)
            )
            await conn.commit()

    async def save_summary(self, session_id: str, summary: CompressedMemory):
        """Save a compression summary to the database.

        Args:
            session_id: Session ID
            summary: CompressedMemory object
        """
        await self._ensure_db()
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT summaries FROM sessions WHERE id = ?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    logger.warning(f"Session {session_id} not found")
                    return

            summaries = json.loads(row[0]) if row[0] else []
            summaries.append(
                {
                    "summary": summary.summary,
                    "preserved_messages": [
                        {"role": msg.role, "content": self._serialize_content(msg.content)}
                        for msg in summary.preserved_messages
                    ],
                    "original_message_count": summary.original_message_count,
                    "original_tokens": summary.original_tokens,
                    "compressed_tokens": summary.compressed_tokens,
                    "compression_ratio": summary.compression_ratio,
                    "metadata": summary.metadata,
                    "created_at": summary.created_at.isoformat(),
                }
            )

            await conn.execute(
                "UPDATE sessions SET summaries = ? WHERE id = ?",
                (json.dumps(summaries), session_id),
            )
            await conn.commit()

    def _serialize_content(self, content):
        """Serialize message content, handling complex objects.

        Args:
            content: Message content (can be string, list, or dict)

        Returns:
            JSON-serializable content
        """
        if content is None:
            return None
        elif isinstance(content, str):
            return content
        elif isinstance(content, (list, dict)):
            # Content is already a structure, ensure it's JSON-serializable
            # Convert any non-serializable objects to strings
            try:
                json.dumps(content)  # Test if serializable
                return content
            except (TypeError, ValueError):
                # If not serializable, convert to string
                return str(content)
        else:
            # Unknown type, convert to string
            return str(content)

    def _serialize_message(self, message: LLMMessage) -> Dict[str, Any]:
        """Serialize an LLMMessage to a JSON-serializable dict.

        Handles both new format (with tool_calls, tool_call_id, name) and
        legacy format (content only).

        Args:
            message: LLMMessage to serialize

        Returns:
            JSON-serializable dict
        """
        result = {
            "role": message.role,
            "content": self._serialize_content(message.content),
        }

        # Add new format fields if present
        # For assistant messages, always include tool_calls (even if None) for completeness
        if message.role == "assistant":
            result["tool_calls"] = (
                message.tool_calls
                if (hasattr(message, "tool_calls") and message.tool_calls)
                else None
            )
        elif hasattr(message, "tool_calls") and message.tool_calls:
            result["tool_calls"] = message.tool_calls

        if hasattr(message, "tool_call_id") and message.tool_call_id:
            result["tool_call_id"] = message.tool_call_id

        if hasattr(message, "name") and message.name:
            result["name"] = message.name

        return result

    def _deserialize_message(self, data: Dict[str, Any]) -> LLMMessage:
        """Deserialize a dict to an LLMMessage.

        Handles both new format and legacy format.

        Args:
            data: Dict with message data

        Returns:
            LLMMessage instance
        """
        return LLMMessage(
            role=data["role"],
            content=data.get("content"),
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
        )

    async def save_memory(
        self,
        session_id: str,
        system_messages: List[LLMMessage],
        messages: List[LLMMessage],
        summaries: List[CompressedMemory],
    ):
        """Save complete memory state to the database.

        This method replaces the entire memory state for a session,
        including system messages, short-term messages, and summaries.

        Args:
            session_id: Session ID
            system_messages: List of system messages
            messages: List of regular messages (short-term memory)
            summaries: List of compressed memory summaries
        """
        await self._ensure_db()
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT id FROM sessions WHERE id = ?", (session_id,)
            ) as cursor:
                if not await cursor.fetchone():
                    logger.warning(f"Session {session_id} not found")
                    return

            system_messages_json = json.dumps(
                [self._serialize_message(msg) for msg in system_messages]
            )

            messages_list = []
            for msg in messages:
                msg_data = self._serialize_message(msg)
                msg_data["tokens"] = 0
                messages_list.append(msg_data)
            messages_json = json.dumps(messages_list)

            summaries_json = json.dumps(
                [
                    {
                        "summary": summary.summary,
                        "preserved_messages": [
                            self._serialize_message(msg) for msg in summary.preserved_messages
                        ],
                        "original_message_count": summary.original_message_count,
                        "original_tokens": summary.original_tokens,
                        "compressed_tokens": summary.compressed_tokens,
                        "compression_ratio": summary.compression_ratio,
                        "metadata": summary.metadata,
                        "created_at": summary.created_at.isoformat(),
                    }
                    for summary in summaries
                ]
            )

            await conn.execute(
                """
                UPDATE sessions
                SET system_messages = ?,
                    messages = ?,
                    summaries = ?
                WHERE id = ?
                """,
                (system_messages_json, messages_json, summaries_json, session_id),
            )
            await conn.commit()
            logger.debug(
                f"Saved memory for session {session_id}: "
                f"{len(system_messages)} system msgs, "
                f"{len(messages)} messages, "
                f"{len(summaries)} summaries"
            )

    async def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load complete session state.

        Args:
            session_id: Session ID

        Returns:
            Dictionary with session data:
            {
                "config": None,  # Config removed in simplified version
                "system_messages": [LLMMessage],
                "messages": [LLMMessage],
                "summaries": [CompressedMemory],
                "stats": {...}
            }
        """
        await self._ensure_db()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cursor:
                session_row = await cursor.fetchone()

            if not session_row:
                logger.warning(f"Session {session_id} not found")
                return None

            # Parse system messages from JSON using new format
            system_messages_data = (
                json.loads(session_row["system_messages"]) if session_row["system_messages"] else []
            )
            system_messages = [self._deserialize_message(msg) for msg in system_messages_data]

            # Parse regular messages from JSON using new format
            messages_data = json.loads(session_row["messages"]) if session_row["messages"] else []
            messages = [self._deserialize_message(msg) for msg in messages_data]

            # Parse summaries from JSON
            summaries_data = (
                json.loads(session_row["summaries"]) if session_row["summaries"] else []
            )
            summaries = []
            for summary_data in summaries_data:
                preserved_msgs = [
                    self._deserialize_message(m) for m in summary_data.get("preserved_messages", [])
                ]

                summaries.append(
                    CompressedMemory(
                        summary=summary_data.get("summary", ""),
                        preserved_messages=preserved_msgs,
                        original_message_count=summary_data.get("original_message_count", 0),
                        original_tokens=summary_data.get("original_tokens", 0),
                        compressed_tokens=summary_data.get("compressed_tokens", 0),
                        compression_ratio=summary_data.get("compression_ratio", 0.0),
                        metadata=summary_data.get("metadata", {}),
                        created_at=(
                            datetime.fromisoformat(summary_data["created_at"])
                            if "created_at" in summary_data
                            else datetime.now()
                        ),
                    )
                )

            return {
                "config": None,  # Config management removed in simplified version
                "system_messages": system_messages,
                "messages": messages,
                "summaries": summaries,
                "stats": {
                    "created_at": session_row["created_at"],
                    "compression_count": len(summaries),
                },
            }

    async def list_sessions(
        self, limit: int = 50, offset: int = 0, order_by: str = "created_at"
    ) -> List[Dict[str, Any]]:
        """List all sessions.

        Args:
            limit: Maximum number of sessions to return
            offset: Offset for pagination
            order_by: Column to order by (created_at only in simplified version)

        Returns:
            List of session summaries
        """
        await self._ensure_db()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row

            if order_by not in ["created_at"]:
                order_by = "created_at"

            async with conn.execute(
                f"""
                SELECT id, created_at, messages, system_messages, summaries
                FROM sessions
                ORDER BY {order_by} DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ) as cursor:
                rows = await cursor.fetchall()

            sessions = []
            for row in rows:
                messages_data = json.loads(row["messages"]) if row["messages"] else []
                system_messages_data = (
                    json.loads(row["system_messages"]) if row["system_messages"] else []
                )
                summaries_data = json.loads(row["summaries"]) if row["summaries"] else []

                sessions.append(
                    {
                        "id": row["id"],
                        "created_at": row["created_at"],
                        "message_count": len(messages_data),
                        "system_message_count": len(system_messages_data),
                        "summary_count": len(summaries_data),
                    }
                )

            return sessions

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its data.

        Args:
            session_id: Session ID

        Returns:
            True if deleted, False if not found
        """
        await self._ensure_db()
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            deleted = cursor.rowcount > 0
            await conn.commit()

        if deleted:
            logger.info(f"Deleted session {session_id}")
        else:
            logger.warning(f"Session {session_id} not found for deletion")

        return deleted

    async def get_session_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session statistics.

        Args:
            session_id: Session ID

        Returns:
            Session statistics or None if not found
        """
        await self._ensure_db()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None

            # Parse JSON fields
            messages_data = json.loads(row["messages"]) if row["messages"] else []
            system_messages_data = (
                json.loads(row["system_messages"]) if row["system_messages"] else []
            )
            summaries_data = json.loads(row["summaries"]) if row["summaries"] else []

            # Calculate token statistics from summaries
            total_original_tokens = sum(s.get("original_tokens", 0) for s in summaries_data)
            total_compressed_tokens = sum(s.get("compressed_tokens", 0) for s in summaries_data)
            total_message_tokens = sum(m.get("tokens", 0) for m in messages_data)

            return {
                "session_id": session_id,
                "created_at": row["created_at"],
                "message_count": len(messages_data),
                "system_message_count": len(system_messages_data),
                "summary_count": len(summaries_data),
                "compression_count": len(summaries_data),
                "total_message_tokens": total_message_tokens,
                "total_original_tokens": total_original_tokens,
                "total_compressed_tokens": total_compressed_tokens,
                "token_savings": total_original_tokens - total_compressed_tokens,
            }
