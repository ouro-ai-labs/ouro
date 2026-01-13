"""Persistent storage for memory using embedded SQLite database."""
import sqlite3
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import logging

from llm.base import LLMMessage
from memory.types import MemoryConfig, CompressedMemory

logger = logging.getLogger(__name__)


class MemoryStore:
    """Persistent storage for conversation memory using SQLite.

    Features:
    - Store complete conversation history by session
    - Save/load memory state (messages + summaries)
    - Query historical sessions
    - Debug by inspecting specific sessions
    """

    def __init__(self, db_path: str = "data/memory.db"):
        """Initialize memory store.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path

        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()

        logger.info(f"MemoryStore initialized at {db_path}")

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Sessions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    metadata TEXT,
                    config TEXT,
                    current_tokens INTEGER DEFAULT 0,
                    compression_count INTEGER DEFAULT 0
                )
            """)

            # Messages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tokens INTEGER DEFAULT 0,
                    timestamp TIMESTAMP NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)

            # Create index for efficient querying
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, timestamp)
            """)

            # Summaries table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    preserved_messages TEXT NOT NULL,
                    original_message_count INTEGER DEFAULT 0,
                    original_tokens INTEGER DEFAULT 0,
                    compressed_tokens INTEGER DEFAULT 0,
                    compression_ratio REAL DEFAULT 0.0,
                    metadata TEXT,
                    created_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)

            # Create index for summaries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_summaries_session
                ON summaries(session_id, created_at)
            """)

            # System messages table (separate for clarity)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)

            conn.commit()
            logger.debug("Database schema initialized")

    def create_session(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        config: Optional[MemoryConfig] = None
    ) -> str:
        """Create a new session.

        Args:
            metadata: Optional session metadata (description, tags, etc.)
            config: Memory configuration for this session

        Returns:
            Session ID (UUID)
        """
        session_id = str(uuid.uuid4())
        now = datetime.now()

        # Serialize config
        config_json = None
        if config:
            config_dict = {
                "max_context_tokens": config.max_context_tokens,
                "target_working_memory_tokens": config.target_working_memory_tokens,
                "compression_threshold": config.compression_threshold,
                "short_term_message_count": config.short_term_message_count,
                "short_term_min_message_count": config.short_term_min_message_count,
                "compression_ratio": config.compression_ratio,
                "preserve_tool_calls": config.preserve_tool_calls,
                "preserve_system_prompts": config.preserve_system_prompts,
            }
            config_json = json.dumps(config_dict)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sessions (id, created_at, updated_at, metadata, config)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    now,
                    now,
                    json.dumps(metadata) if metadata else None,
                    config_json,
                )
            )
            conn.commit()

        logger.info(f"Created session {session_id}")
        return session_id

    def save_message(
        self,
        session_id: str,
        message: LLMMessage,
        tokens: int = 0
    ):
        """Save a message to the database.

        Args:
            session_id: Session ID
            message: LLMMessage to save
            tokens: Token count for this message
        """
        now = datetime.now()

        # Serialize content (handle both str and list)
        content_json = json.dumps(message.content)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Save message
            if message.role == "system":
                cursor.execute(
                    """
                    INSERT INTO system_messages (session_id, content, timestamp)
                    VALUES (?, ?, ?)
                    """,
                    (session_id, content_json, now)
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO messages (session_id, role, content, tokens, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, message.role, content_json, tokens, now)
                )

            # Update session updated_at
            cursor.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id)
            )

            conn.commit()

    def save_summary(
        self,
        session_id: str,
        summary: CompressedMemory
    ):
        """Save a compression summary to the database.

        Args:
            session_id: Session ID
            summary: CompressedMemory object
        """
        now = datetime.now()

        # Serialize preserved messages
        preserved_json = json.dumps([
            {"role": msg.role, "content": msg.content}
            for msg in summary.preserved_messages
        ])

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO summaries (
                    session_id, summary_text, preserved_messages,
                    original_message_count, original_tokens, compressed_tokens,
                    compression_ratio, metadata, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    summary.summary,
                    preserved_json,
                    summary.original_message_count,
                    summary.original_tokens,
                    summary.compressed_tokens,
                    summary.compression_ratio,
                    json.dumps(summary.metadata),
                    now,
                )
            )

            # Update session stats
            cursor.execute(
                """
                UPDATE sessions
                SET compression_count = compression_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, session_id)
            )

            conn.commit()

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load complete session state.

        Args:
            session_id: Session ID

        Returns:
            Dictionary with session data:
            {
                "metadata": {...},
                "config": MemoryConfig,
                "system_messages": [LLMMessage],
                "messages": [LLMMessage],
                "summaries": [CompressedMemory],
                "stats": {...}
            }
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Load session info
            cursor.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,)
            )
            session_row = cursor.fetchone()

            if not session_row:
                logger.warning(f"Session {session_id} not found")
                return None

            # Parse config
            config = None
            if session_row["config"]:
                config_dict = json.loads(session_row["config"])
                config = MemoryConfig(**config_dict)

            # Load system messages
            cursor.execute(
                """
                SELECT content, timestamp
                FROM system_messages
                WHERE session_id = ?
                ORDER BY timestamp
                """,
                (session_id,)
            )
            system_messages = [
                LLMMessage(role="system", content=json.loads(row["content"]))
                for row in cursor.fetchall()
            ]

            # Load regular messages
            cursor.execute(
                """
                SELECT role, content, tokens, timestamp
                FROM messages
                WHERE session_id = ?
                ORDER BY timestamp
                """,
                (session_id,)
            )
            messages = [
                LLMMessage(role=row["role"], content=json.loads(row["content"]))
                for row in cursor.fetchall()
            ]

            # Load summaries
            cursor.execute(
                """
                SELECT summary_text, preserved_messages, original_message_count,
                       original_tokens, compressed_tokens, compression_ratio,
                       metadata, created_at
                FROM summaries
                WHERE session_id = ?
                ORDER BY created_at
                """,
                (session_id,)
            )
            summaries = []
            for row in cursor.fetchall():
                preserved_msgs = [
                    LLMMessage(role=m["role"], content=m["content"])
                    for m in json.loads(row["preserved_messages"])
                ]

                summaries.append(CompressedMemory(
                    summary=row["summary_text"],
                    preserved_messages=preserved_msgs,
                    original_message_count=row["original_message_count"],
                    original_tokens=row["original_tokens"],
                    compressed_tokens=row["compressed_tokens"],
                    compression_ratio=row["compression_ratio"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                    created_at=datetime.fromisoformat(row["created_at"])
                ))

            return {
                "metadata": json.loads(session_row["metadata"]) if session_row["metadata"] else {},
                "config": config,
                "system_messages": system_messages,
                "messages": messages,
                "summaries": summaries,
                "stats": {
                    "created_at": session_row["created_at"],
                    "updated_at": session_row["updated_at"],
                    "current_tokens": session_row["current_tokens"],
                    "compression_count": session_row["compression_count"],
                }
            }

    def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "updated_at"
    ) -> List[Dict[str, Any]]:
        """List all sessions.

        Args:
            limit: Maximum number of sessions to return
            offset: Offset for pagination
            order_by: Column to order by (created_at or updated_at)

        Returns:
            List of session summaries
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Validate order_by
            if order_by not in ["created_at", "updated_at"]:
                order_by = "updated_at"

            cursor.execute(
                f"""
                SELECT
                    s.id, s.created_at, s.updated_at, s.metadata,
                    s.compression_count,
                    COUNT(DISTINCT m.id) as message_count,
                    COUNT(DISTINCT sm.id) as system_message_count,
                    COUNT(DISTINCT su.id) as summary_count
                FROM sessions s
                LEFT JOIN messages m ON s.id = m.session_id
                LEFT JOIN system_messages sm ON s.id = sm.session_id
                LEFT JOIN summaries su ON s.id = su.session_id
                GROUP BY s.id
                ORDER BY s.{order_by} DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset)
            )

            sessions = []
            for row in cursor.fetchall():
                sessions.append({
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    "message_count": row["message_count"],
                    "system_message_count": row["system_message_count"],
                    "summary_count": row["summary_count"],
                    "compression_count": row["compression_count"],
                })

            return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its data.

        Args:
            session_id: Session ID

        Returns:
            True if deleted, False if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            deleted = cursor.rowcount > 0
            conn.commit()

        if deleted:
            logger.info(f"Deleted session {session_id}")
        else:
            logger.warning(f"Session {session_id} not found for deletion")

        return deleted

    def update_session_metadata(
        self,
        session_id: str,
        metadata: Dict[str, Any]
    ) -> bool:
        """Update session metadata.

        Args:
            session_id: Session ID
            metadata: New metadata

        Returns:
            True if updated, False if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE sessions
                SET metadata = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(metadata), datetime.now(), session_id)
            )
            updated = cursor.rowcount > 0
            conn.commit()

        return updated

    def get_session_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session statistics.

        Args:
            session_id: Session ID

        Returns:
            Session statistics or None if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    s.created_at, s.updated_at, s.compression_count,
                    s.current_tokens, s.metadata,
                    COUNT(DISTINCT m.id) as message_count,
                    SUM(m.tokens) as total_message_tokens,
                    COUNT(DISTINCT sm.id) as system_message_count,
                    COUNT(DISTINCT su.id) as summary_count,
                    SUM(su.original_tokens) as total_original_tokens,
                    SUM(su.compressed_tokens) as total_compressed_tokens
                FROM sessions s
                LEFT JOIN messages m ON s.id = m.session_id
                LEFT JOIN system_messages sm ON s.id = sm.session_id
                LEFT JOIN summaries su ON s.id = su.session_id
                WHERE s.id = ?
                GROUP BY s.id
                """,
                (session_id,)
            )

            row = cursor.fetchone()
            if not row:
                return None

            return {
                "session_id": session_id,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                "message_count": row["message_count"] or 0,
                "system_message_count": row["system_message_count"] or 0,
                "summary_count": row["summary_count"] or 0,
                "compression_count": row["compression_count"] or 0,
                "current_tokens": row["current_tokens"] or 0,
                "total_message_tokens": row["total_message_tokens"] or 0,
                "total_original_tokens": row["total_original_tokens"] or 0,
                "total_compressed_tokens": row["total_compressed_tokens"] or 0,
                "token_savings": (row["total_original_tokens"] or 0) - (row["total_compressed_tokens"] or 0),
            }
