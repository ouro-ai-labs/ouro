"""Scoped memory view for hierarchical memory management.

.. deprecated::
    This module is deprecated in favor of `memory.graph.MemoryGraph` which
    provides a more flexible graph-based memory structure with support for
    multiple parent nodes and dynamic linking. See RFC-004 for details.

    Migration guide:
    - Replace `ScopedMemoryView` with `MemoryNode` from `memory.graph`
    - Replace `MemoryScope` enum usage with `metadata["scope"]` in MemoryNode
    - Use `MemoryGraph` for creating and managing memory nodes
"""

import warnings
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

from llm.message_types import LLMMessage

if TYPE_CHECKING:
    from .manager import MemoryManager


def _warn_deprecated():
    """Issue a deprecation warning for this module."""
    warnings.warn(
        "memory.scope is deprecated, use memory.graph.MemoryGraph instead. "
        "See RFC-004 for migration guide.",
        DeprecationWarning,
        stacklevel=3,
    )


class MemoryScope(Enum):
    """Memory scope levels for hierarchical context management."""

    GLOBAL = "global"
    EXPLORATION = "exploration"
    EXECUTION = "execution"
    STEP = "step"


class ScopedMemoryView:
    """Provides scoped access to memory without duplication.

    .. deprecated::
        Use `memory.graph.MemoryNode` and `memory.graph.MemoryGraph` instead.
        This class will be removed in a future version.

    This class enables hierarchical memory management where each scope
    (exploration, execution, step) maintains its own local messages while
    having access to parent scope summaries.
    """

    def __init__(
        self,
        manager: "MemoryManager",
        scope: MemoryScope,
        parent_view: Optional["ScopedMemoryView"] = None,
    ):
        """Initialize a scoped memory view.

        Args:
            manager: The global MemoryManager instance.
            scope: The scope level for this view.
            parent_view: Optional parent scope for context inheritance.
        """
        _warn_deprecated()
        self.manager = manager
        self.scope = scope
        self.parent_view = parent_view
        self._local_messages: List[LLMMessage] = []
        self._scope_summary: Optional[str] = None

    def add_message(self, message: LLMMessage) -> None:
        """Add a message to this scope.

        Args:
            message: The message to add to local scope.
        """
        self._local_messages.append(message)

    def get_messages(self) -> List[LLMMessage]:
        """Get all messages in this scope.

        Returns:
            List of messages in this scope.
        """
        return self._local_messages.copy()

    def get_context(self, include_parent: bool = True) -> List[LLMMessage]:
        """Get context for this scope, optionally including parent summary.

        Args:
            include_parent: Whether to include parent scope summary.

        Returns:
            List of messages forming the context.
        """
        context = []

        # Include parent summary if requested and available
        if include_parent and self.parent_view:
            summary = self.parent_view.get_summary()
            if summary:
                context.append(LLMMessage(role="user", content=f"[Previous Context]\n{summary}"))

        # Add local messages
        context.extend(self._local_messages)
        return context

    def get_summary(self) -> str:
        """Get a summary of this scope's messages.

        If a summary has been explicitly set, returns that.
        Otherwise, generates a basic summary from recent messages.

        Returns:
            Summary string of this scope's context.
        """
        if self._scope_summary:
            return self._scope_summary

        # Generate basic summary from last few messages
        if not self._local_messages:
            return ""

        parts = []
        for msg in self._local_messages[-5:]:
            content = str(msg.content)
            truncated = content[:200] + "..." if len(content) > 200 else content
            parts.append(f"{msg.role}: {truncated}")
        return "\n".join(parts)

    def set_summary(self, summary: str) -> None:
        """Set a compressed summary for this scope.

        Args:
            summary: The summary text to set.
        """
        self._scope_summary = summary

    async def commit_to_global(self) -> None:
        """Commit this scope's summary to the global memory.

        This saves the scope summary as a message in the global MemoryManager,
        preserving context for future reference.
        """
        summary = self.get_summary()
        if summary:
            await self.manager.add_message(
                LLMMessage(
                    role="assistant",
                    content=f"[{self.scope.value.title()} Summary]\n{summary}",
                )
            )

    def clear(self) -> None:
        """Clear all local messages and summary."""
        self._local_messages.clear()
        self._scope_summary = None

    def message_count(self) -> int:
        """Get the number of messages in this scope.

        Returns:
            Count of local messages.
        """
        return len(self._local_messages)
