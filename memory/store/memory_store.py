"""Abstract base class for memory persistence backends."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from llm.message_types import LLMMessage


class MemoryStore(ABC):
    """Abstract interface for memory persistence.

    All memory storage implementations (YAML files, SQLite, etc.)
    must implement this interface.
    """

    @abstractmethod
    async def create_session(self, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Create a new session.

        Args:
            metadata: Optional session metadata

        Returns:
            Session ID (UUID string)
        """

    @abstractmethod
    async def save_message(self, session_id: str, message: LLMMessage, tokens: int = 0) -> None:
        """Save a single message to a session.

        Args:
            session_id: Session ID
            message: LLMMessage to save
            tokens: Token count for this message
        """

    @abstractmethod
    async def save_memory(
        self,
        session_id: str,
        system_messages: List[LLMMessage],
        messages: List[LLMMessage],
    ) -> None:
        """Save complete memory state (replaces existing data).

        Args:
            session_id: Session ID
            system_messages: List of system messages
            messages: List of regular messages
        """

    @abstractmethod
    async def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load complete session state.

        Args:
            session_id: Session ID

        Returns:
            Dictionary with session data or None if not found:
            {
                "system_messages": [LLMMessage],
                "messages": [LLMMessage],
                "stats": {"created_at": str, ...}
            }
        """

    @abstractmethod
    async def list_sessions(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List sessions ordered by most recent first.

        Args:
            limit: Maximum number of sessions to return
            offset: Offset for pagination

        Returns:
            List of session summaries with id, created_at, message_count, etc.
        """

    @abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its data.

        Args:
            session_id: Session ID

        Returns:
            True if deleted, False if not found
        """

    @abstractmethod
    async def get_session_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session statistics.

        Args:
            session_id: Session ID

        Returns:
            Session statistics or None if not found
        """
