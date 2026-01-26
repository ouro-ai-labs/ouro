"""Graph-based memory system for composable agent architecture.

This module replaces the hierarchical ScopedMemoryView with a flexible
graph structure supporting multiple parent nodes and dynamic linking.
"""

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from llm.message_types import LLMMessage

if TYPE_CHECKING:
    from llm import LiteLLMAdapter


@dataclass
class MemoryNode:
    """A node in the memory graph representing a context scope.

    Each node maintains its own message history while being able to
    access context from parent nodes through summaries.

    Attributes:
        id: Unique identifier for this node
        messages: Local messages in this scope
        parent_ids: IDs of parent nodes (supports multiple parents)
        child_ids: IDs of child nodes
        summary: Compressed summary of this node's context
        metadata: Additional node metadata (agent_id, task, etc.)
        created_at: When this node was created
    """

    id: str
    messages: List[LLMMessage] = field(default_factory=list)
    parent_ids: List[str] = field(default_factory=list)
    child_ids: List[str] = field(default_factory=list)
    summary: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def add_message(self, message: LLMMessage) -> None:
        """Add a message to this node's local history."""
        self.messages.append(message)

    def get_local_messages(self) -> List[LLMMessage]:
        """Get messages local to this node."""
        return self.messages.copy()

    def message_count(self) -> int:
        """Get the number of local messages."""
        return len(self.messages)

    def set_summary(self, summary: str) -> None:
        """Set or update the summary for this node."""
        self.summary = summary

    def clear(self) -> None:
        """Clear all local messages and summary."""
        self.messages.clear()
        self.summary = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize node to dictionary for persistence."""
        return {
            "id": self.id,
            "messages": [msg.to_dict() for msg in self.messages],
            "parent_ids": self.parent_ids,
            "child_ids": self.child_ids,
            "summary": self.summary,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryNode":
        """Deserialize node from dictionary."""
        messages = [LLMMessage.from_dict(m) for m in data.get("messages", [])]
        created_at = (
            datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now()
        )
        return cls(
            id=data["id"],
            messages=messages,
            parent_ids=data.get("parent_ids", []),
            child_ids=data.get("child_ids", []),
            summary=data.get("summary"),
            metadata=data.get("metadata", {}),
            created_at=created_at,
        )


class MemoryGraph:
    """Graph-based memory management for composable agents.

    Supports:
    - Multiple parent nodes (for merging parallel exploration results)
    - Dynamic node linking and unlinking
    - Context construction from ancestor chains
    - Incremental summarization and compression
    """

    def __init__(self, llm: Optional["LiteLLMAdapter"] = None):
        """Initialize the memory graph.

        Args:
            llm: Optional LLM adapter for summarization
        """
        self.nodes: Dict[str, MemoryNode] = {}
        self.llm = llm
        self._root_id: Optional[str] = None

    @property
    def root_id(self) -> Optional[str]:
        """Get the root node ID."""
        return self._root_id

    def create_node(
        self,
        parent_id: Optional[str] = None,
        parent_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryNode:
        """Create a new memory node.

        Args:
            parent_id: Single parent node ID (convenience for single-parent case)
            parent_ids: List of parent node IDs (for multiple parents)
            metadata: Optional metadata for the node

        Returns:
            The newly created node
        """
        node_id = str(uuid.uuid4())

        # Resolve parent IDs
        resolved_parent_ids: List[str] = []
        if parent_ids:
            resolved_parent_ids = parent_ids.copy()
        elif parent_id:
            resolved_parent_ids = [parent_id]

        # Validate parent IDs exist
        for pid in resolved_parent_ids:
            if pid not in self.nodes:
                raise ValueError(f"Parent node {pid} does not exist")

        node = MemoryNode(
            id=node_id,
            parent_ids=resolved_parent_ids,
            metadata=metadata or {},
        )
        self.nodes[node_id] = node

        # Update parent nodes' child lists
        for pid in resolved_parent_ids:
            self.nodes[pid].child_ids.append(node_id)

        # Set as root if first node
        if self._root_id is None:
            self._root_id = node_id

        return node

    def create_root_node(self, metadata: Optional[Dict[str, Any]] = None) -> MemoryNode:
        """Create or get the root node.

        Args:
            metadata: Optional metadata for the root node

        Returns:
            The root node
        """
        if self._root_id is not None:
            return self.nodes[self._root_id]

        return self.create_node(metadata=metadata)

    def get_node(self, node_id: str) -> Optional[MemoryNode]:
        """Get a node by ID.

        Args:
            node_id: The node ID to look up

        Returns:
            The node or None if not found
        """
        return self.nodes.get(node_id)

    def link_nodes(self, child_id: str, parent_id: str) -> None:
        """Link a child node to an additional parent.

        This enables merging context from multiple sources (e.g., parallel exploration).

        Args:
            child_id: The child node ID
            parent_id: The parent node ID to link to

        Raises:
            ValueError: If either node doesn't exist or would create a cycle
        """
        if child_id not in self.nodes:
            raise ValueError(f"Child node {child_id} does not exist")
        if parent_id not in self.nodes:
            raise ValueError(f"Parent node {parent_id} does not exist")

        # Check for cycles using BFS
        if self._would_create_cycle(child_id, parent_id):
            raise ValueError(f"Linking {child_id} to {parent_id} would create a cycle")

        child = self.nodes[child_id]
        parent = self.nodes[parent_id]

        if parent_id not in child.parent_ids:
            child.parent_ids.append(parent_id)
        if child_id not in parent.child_ids:
            parent.child_ids.append(child_id)

    def unlink_nodes(self, child_id: str, parent_id: str) -> None:
        """Remove a parent-child link.

        Args:
            child_id: The child node ID
            parent_id: The parent node ID to unlink from
        """
        if child_id in self.nodes and parent_id in self.nodes:
            child = self.nodes[child_id]
            parent = self.nodes[parent_id]

            if parent_id in child.parent_ids:
                child.parent_ids.remove(parent_id)
            if child_id in parent.child_ids:
                parent.child_ids.remove(child_id)

    def _would_create_cycle(self, child_id: str, parent_id: str) -> bool:
        """Check if adding a link would create a cycle.

        Uses BFS to detect if parent_id is reachable from child_id
        (which would mean adding child_id as a child of parent_id creates a cycle).

        Args:
            child_id: The proposed child node
            parent_id: The proposed parent node

        Returns:
            True if adding the link would create a cycle
        """
        # If child_id can reach parent_id through existing parent links,
        # then adding parent_id as a parent of child_id would create a cycle
        visited: Set[str] = set()
        queue: deque[str] = deque([child_id])

        while queue:
            current = queue.popleft()
            if current == parent_id:
                return True
            if current in visited:
                continue
            visited.add(current)

            node = self.nodes.get(current)
            if node:
                for cid in node.child_ids:
                    if cid not in visited:
                        queue.append(cid)

        return False

    def get_ancestors(self, node_id: str) -> List[MemoryNode]:
        """Get all ancestor nodes in breadth-first order.

        Args:
            node_id: The starting node ID

        Returns:
            List of ancestor nodes (excluding the starting node)
        """
        if node_id not in self.nodes:
            return []

        ancestors: List[MemoryNode] = []
        visited: Set[str] = set()
        queue: deque[str] = deque()

        # Start with immediate parents
        node = self.nodes[node_id]
        for pid in node.parent_ids:
            if pid not in visited:
                queue.append(pid)
                visited.add(pid)

        while queue:
            current_id = queue.popleft()
            current = self.nodes.get(current_id)
            if current:
                ancestors.append(current)
                for pid in current.parent_ids:
                    if pid not in visited:
                        queue.append(pid)
                        visited.add(pid)

        return ancestors

    def get_context_for_llm(self, node_id: str) -> List[LLMMessage]:
        """Build LLM context from a node and its ancestors.

        Context includes:
        1. Summaries from all ancestors (oldest first)
        2. Local messages from the current node

        Args:
            node_id: The node to build context for

        Returns:
            List of messages suitable for LLM call
        """
        if node_id not in self.nodes:
            return []

        node = self.nodes[node_id]

        # Get ancestor summaries (reverse to get oldest first)
        ancestors = self.get_ancestors(node_id)
        context: List[LLMMessage] = [
            LLMMessage(
                role="user",
                content=f"[Context from {ancestor.metadata.get('scope', 'previous')}]\n{ancestor.summary}",
            )
            for ancestor in reversed(ancestors)
            if ancestor.summary
        ]

        # Add local messages
        context.extend(node.get_local_messages())

        return context

    async def summarize_node(
        self,
        node_id: str,
        force: bool = False,
    ) -> Optional[str]:
        """Generate a summary for a node using the LLM.

        Args:
            node_id: The node to summarize
            force: If True, regenerate even if summary exists

        Returns:
            The generated summary or None if no LLM is available
        """
        if not self.llm:
            return None

        node = self.nodes.get(node_id)
        if not node:
            return None

        if node.summary and not force:
            return node.summary

        if not node.messages:
            return None

        # Build prompt for summarization
        messages_text = []
        for msg in node.messages[-20:]:  # Limit to recent messages
            content = str(msg.content) if msg.content else ""
            messages_text.append(f"{msg.role}: {content[:500]}")

        prompt = f"""Summarize the following conversation concisely, preserving key information and decisions:

{chr(10).join(messages_text)}

Summary:"""

        try:
            response = await self.llm.call_async(
                messages=[LLMMessage(role="user", content=prompt)],
                max_tokens=500,
            )
            summary = self.llm.extract_text(response)
            node.set_summary(summary)
            return summary
        except Exception:
            return None

    async def merge_nodes(
        self,
        source_ids: List[str],
        target_id: str,
    ) -> None:
        """Merge summaries from multiple source nodes into a target.

        Used for combining parallel exploration results.

        Args:
            source_ids: List of source node IDs to merge from
            target_id: Target node ID to merge into
        """
        if target_id not in self.nodes:
            return

        target = self.nodes[target_id]

        # Collect summaries from sources
        summaries = []
        for sid in source_ids:
            source = self.nodes.get(sid)
            if source:
                if not source.summary and source.messages:
                    await self.summarize_node(sid)
                if source.summary:
                    scope = source.metadata.get("scope", f"source_{sid[:8]}")
                    summaries.append(f"[{scope}]\n{source.summary}")

        if summaries:
            # Add merged context to target
            merged_content = "\n\n".join(summaries)
            target.add_message(
                LLMMessage(
                    role="user",
                    content=f"[Merged Context]\n{merged_content}",
                )
            )

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and clean up references.

        Args:
            node_id: The node ID to delete

        Returns:
            True if deleted, False if not found
        """
        if node_id not in self.nodes:
            return False

        node = self.nodes[node_id]

        # Remove from parent's child lists
        for pid in node.parent_ids:
            parent = self.nodes.get(pid)
            if parent and node_id in parent.child_ids:
                parent.child_ids.remove(node_id)

        # Remove from child's parent lists
        for cid in node.child_ids:
            child = self.nodes.get(cid)
            if child and node_id in child.parent_ids:
                child.parent_ids.remove(node_id)

        # Delete the node
        del self.nodes[node_id]

        # Update root if necessary
        if self._root_id == node_id:
            self._root_id = None

        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the entire graph to a dictionary."""
        return {
            "root_id": self._root_id,
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
        }

    @classmethod
    def from_dict(
        cls, data: Dict[str, Any], llm: Optional["LiteLLMAdapter"] = None
    ) -> "MemoryGraph":
        """Deserialize a graph from a dictionary.

        Args:
            data: Serialized graph data
            llm: Optional LLM adapter

        Returns:
            Reconstructed MemoryGraph
        """
        graph = cls(llm=llm)
        graph._root_id = data.get("root_id")
        graph.nodes = {
            nid: MemoryNode.from_dict(ndata) for nid, ndata in data.get("nodes", {}).items()
        }
        return graph

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the memory graph."""
        total_messages = sum(n.message_count() for n in self.nodes.values())
        nodes_with_summary = sum(1 for n in self.nodes.values() if n.summary)

        return {
            "node_count": len(self.nodes),
            "total_messages": total_messages,
            "nodes_with_summary": nodes_with_summary,
            "root_id": self._root_id,
        }
