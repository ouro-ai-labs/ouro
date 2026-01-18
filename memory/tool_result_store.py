"""External storage for large tool results."""

import hashlib
import logging
import sqlite3
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class ToolResultStore:
    """Store large tool results externally with SQLite backend.

    This allows keeping full tool results accessible while only storing
    summaries in the main memory context.
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize tool result store.

        Args:
            db_path: Path to SQLite database file. If None, uses in-memory database.
        """
        self.db_path = db_path or ":memory:"
        self.conn: sqlite3.Connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        self.conn.row_factory = sqlite3.Row

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_results (
                id TEXT PRIMARY KEY,
                tool_call_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                summary TEXT,
                token_count INTEGER,
                created_at TIMESTAMP NOT NULL,
                accessed_at TIMESTAMP,
                access_count INTEGER DEFAULT 0
            )
        """
        )

        # Index for faster lookups
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tool_call_id
            ON tool_results(tool_call_id)
        """
        )

        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_created_at
            ON tool_results(created_at)
        """
        )

        self.conn.commit()
        logger.info(f"Initialized tool result store at {self.db_path}")

    def store_result(
        self,
        tool_call_id: str,
        tool_name: str,
        content: str,
        summary: Optional[str] = None,
        token_count: Optional[int] = None,
    ) -> str:
        """Store a tool result externally.

        Args:
            tool_call_id: ID of the tool call that produced this result
            tool_name: Name of the tool
            content: Full content to store
            summary: Optional summary (if None, will generate simple summary)
            token_count: Optional token count of content

        Returns:
            Result ID for retrieval
        """
        # Generate unique ID based on content hash
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        result_id = f"{tool_name}_{content_hash}"

        # Check if already stored
        existing = self.conn.execute(
            "SELECT id FROM tool_results WHERE content_hash = ?", (content_hash,)
        ).fetchone()

        if existing:
            logger.debug(f"Tool result already stored: {result_id}")
            return result_id

        # Generate summary if not provided
        if summary is None:
            summary = self._generate_simple_summary(content, tool_name)

        # Estimate tokens if not provided
        if token_count is None:
            token_count = int(len(content) / 3.5)

        # Store result
        try:
            self.conn.execute(
                """
                INSERT INTO tool_results
                (id, tool_call_id, tool_name, content, content_hash, summary, token_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    result_id,
                    tool_call_id,
                    tool_name,
                    content,
                    content_hash,
                    summary,
                    token_count,
                    datetime.now(),
                ),
            )
            self.conn.commit()
            logger.info(
                f"Stored tool result {result_id}: {len(content)} chars, {token_count} tokens"
            )
            return result_id

        except sqlite3.IntegrityError as e:
            logger.warning(f"Failed to store tool result: {e}")
            # Return existing ID if duplicate
            return result_id

    def retrieve_result(self, result_id: str) -> Optional[str]:
        """Retrieve full content of a stored result.

        Args:
            result_id: ID returned by store_result()

        Returns:
            Full content, or None if not found
        """
        row = self.conn.execute(
            "SELECT content FROM tool_results WHERE id = ?", (result_id,)
        ).fetchone()

        if row:
            # Update access tracking
            self.conn.execute(
                """
                UPDATE tool_results
                SET accessed_at = ?, access_count = access_count + 1
                WHERE id = ?
            """,
                (datetime.now(), result_id),
            )
            self.conn.commit()

            logger.debug(f"Retrieved tool result {result_id}")
            return row["content"]

        logger.warning(f"Tool result not found: {result_id}")
        return None

    def get_summary(self, result_id: str) -> Optional[str]:
        """Get summary of a stored result without retrieving full content.

        Args:
            result_id: ID returned by store_result()

        Returns:
            Summary text, or None if not found
        """
        row = self.conn.execute(
            "SELECT summary, tool_name, token_count FROM tool_results WHERE id = ?",
            (result_id,),
        ).fetchone()

        if row:
            return row["summary"]

        return None

    def get_metadata(self, result_id: str) -> Optional[dict]:
        """Get metadata about a stored result.

        Args:
            result_id: ID returned by store_result()

        Returns:
            Dictionary with metadata, or None if not found
        """
        row = self.conn.execute(
            """
            SELECT tool_call_id, tool_name, token_count, created_at,
                   accessed_at, access_count, length(content) as content_length
            FROM tool_results
            WHERE id = ?
        """,
            (result_id,),
        ).fetchone()

        if row:
            return dict(row)

        return None

    def format_reference(self, result_id: str, include_summary: bool = True) -> str:
        """Format a reference to a stored result for inclusion in memory.

        Args:
            result_id: ID returned by store_result()
            include_summary: Whether to include the summary

        Returns:
            Formatted reference string
        """
        metadata = self.get_metadata(result_id)
        if not metadata:
            return f"[Tool Result #{result_id} - not found]"

        lines = [
            f"[Tool Result #{result_id}]",
            f"Tool: {metadata['tool_name']}",
            f"Size: {metadata['content_length']} chars (~{metadata['token_count']} tokens)",
            f"Stored: {metadata['created_at']}",
        ]

        if include_summary:
            summary = self.get_summary(result_id)
            if summary:
                lines.append("")
                lines.append("Summary:")
                lines.append(summary)

        lines.append("")
        lines.append(
            "[Full content available via retrieve_tool_result tool - use this ID to access]"
        )

        return "\n".join(lines)

    def _generate_simple_summary(self, content: str, tool_name: str) -> str:
        """Generate a simple summary of content.

        Args:
            content: Content to summarize
            tool_name: Name of tool that produced content

        Returns:
            Simple summary string
        """
        lines = content.split("\n")
        char_count = len(content)
        line_count = len(lines)

        # Get first few non-empty lines as preview
        preview_lines = []
        for line in lines[:5]:
            if line.strip():
                preview_lines.append(line[:100])
                if len(preview_lines) >= 3:
                    break

        preview = "\n".join(preview_lines)
        if len(preview) > 300:
            preview = preview[:297] + "..."

        return f"""Tool: {tool_name}
Size: {char_count} characters, {line_count} lines

Preview:
{preview}

[Use retrieve_tool_result to access full content]"""

    def cleanup_old_results(self, days: int = 7) -> int:
        """Remove results older than specified days.

        Args:
            days: Remove results older than this many days

        Returns:
            Number of results removed
        """
        cursor = self.conn.execute(
            """
            DELETE FROM tool_results
            WHERE created_at < datetime('now', '-' || ? || ' days')
        """,
            (days,),
        )
        deleted = cursor.rowcount
        self.conn.commit()

        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old tool results (older than {days} days)")

        return deleted

    def get_stats(self) -> dict:
        """Get statistics about stored results.

        Returns:
            Dictionary with statistics
        """
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) as total_results,
                SUM(length(content)) as total_bytes,
                SUM(token_count) as total_tokens,
                AVG(access_count) as avg_access_count,
                MAX(created_at) as latest_created
            FROM tool_results
        """
        ).fetchone()

        return dict(row) if row else {}

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Closed tool result store")

    def __del__(self):
        """Cleanup on deletion."""
        self.close()
