"""Unit tests for MemoryGraph (RFC-004)."""

import pytest

from llm.message_types import LLMMessage
from memory.graph import MemoryGraph, MemoryNode


class TestMemoryNode:
    """Test MemoryNode dataclass."""

    def test_basic_creation(self):
        """Test creating a basic memory node."""
        node = MemoryNode(id="node-1")

        assert node.id == "node-1"
        assert node.messages == []
        assert node.parent_ids == []
        assert node.child_ids == []
        assert node.summary is None
        assert node.metadata == {}

    def test_add_message(self):
        """Test adding messages to a node."""
        node = MemoryNode(id="node-1")

        msg = LLMMessage(role="user", content="Hello")
        node.add_message(msg)

        assert node.message_count() == 1
        assert node.get_local_messages()[0].content == "Hello"

    def test_set_summary(self):
        """Test setting node summary."""
        node = MemoryNode(id="node-1")
        node.set_summary("This is a summary")

        assert node.summary == "This is a summary"

    def test_clear(self):
        """Test clearing a node."""
        node = MemoryNode(id="node-1")
        node.add_message(LLMMessage(role="user", content="Hello"))
        node.set_summary("Summary")

        node.clear()

        assert node.message_count() == 0
        assert node.summary is None

    def test_serialization_roundtrip(self):
        """Test serializing and deserializing a node."""
        node = MemoryNode(
            id="node-1",
            messages=[LLMMessage(role="user", content="Hello")],
            parent_ids=["parent-1"],
            child_ids=["child-1"],
            summary="Test summary",
            metadata={"key": "value"},
        )

        # Serialize
        data = node.to_dict()

        # Deserialize
        restored = MemoryNode.from_dict(data)

        assert restored.id == node.id
        assert len(restored.messages) == 1
        assert restored.messages[0].content == "Hello"
        assert restored.parent_ids == ["parent-1"]
        assert restored.child_ids == ["child-1"]
        assert restored.summary == "Test summary"
        assert restored.metadata["key"] == "value"


class TestMemoryGraphBasics:
    """Test basic MemoryGraph functionality."""

    def test_initialization(self):
        """Test graph initialization."""
        graph = MemoryGraph()

        assert len(graph.nodes) == 0
        assert graph.root_id is None

    def test_create_root_node(self):
        """Test creating root node."""
        graph = MemoryGraph()
        root = graph.create_root_node(metadata={"scope": "root"})

        assert root.id == graph.root_id
        assert graph.get_node(root.id) is root
        assert root.metadata["scope"] == "root"

    def test_create_node_with_parent(self):
        """Test creating node with parent."""
        graph = MemoryGraph()
        root = graph.create_root_node()
        child = graph.create_node(parent_id=root.id)

        assert root.id in child.parent_ids
        assert child.id in root.child_ids

    def test_create_node_with_multiple_parents(self):
        """Test creating node with multiple parents."""
        graph = MemoryGraph()
        root = graph.create_root_node()
        parent1 = graph.create_node(parent_id=root.id)
        parent2 = graph.create_node(parent_id=root.id)

        # Create child with multiple parents
        child = graph.create_node(parent_ids=[parent1.id, parent2.id])

        assert parent1.id in child.parent_ids
        assert parent2.id in child.parent_ids
        assert child.id in parent1.child_ids
        assert child.id in parent2.child_ids

    def test_create_node_invalid_parent(self):
        """Test creating node with nonexistent parent raises error."""
        graph = MemoryGraph()

        with pytest.raises(ValueError, match="does not exist"):
            graph.create_node(parent_id="nonexistent")


class TestMemoryGraphLinks:
    """Test graph linking operations."""

    def test_link_nodes(self):
        """Test linking nodes after creation."""
        graph = MemoryGraph()
        root = graph.create_root_node()
        node1 = graph.create_node(parent_id=root.id)
        node2 = graph.create_node(parent_id=root.id)

        # Link node2 as additional parent of node1
        graph.link_nodes(child_id=node1.id, parent_id=node2.id)

        assert node2.id in node1.parent_ids
        assert node1.id in node2.child_ids

    def test_link_nodes_invalid_child(self):
        """Test linking with invalid child raises error."""
        graph = MemoryGraph()
        root = graph.create_root_node()

        with pytest.raises(ValueError, match="does not exist"):
            graph.link_nodes(child_id="nonexistent", parent_id=root.id)

    def test_link_nodes_invalid_parent(self):
        """Test linking with invalid parent raises error."""
        graph = MemoryGraph()
        root = graph.create_root_node()

        with pytest.raises(ValueError, match="does not exist"):
            graph.link_nodes(child_id=root.id, parent_id="nonexistent")

    def test_link_nodes_cycle_detection(self):
        """Test that cycle detection prevents invalid links."""
        graph = MemoryGraph()
        root = graph.create_root_node()
        child = graph.create_node(parent_id=root.id)
        grandchild = graph.create_node(parent_id=child.id)

        # Attempting to make root a child of grandchild would create cycle
        with pytest.raises(ValueError, match="cycle"):
            graph.link_nodes(child_id=root.id, parent_id=grandchild.id)

    def test_unlink_nodes(self):
        """Test unlinking nodes."""
        graph = MemoryGraph()
        root = graph.create_root_node()
        child = graph.create_node(parent_id=root.id)

        graph.unlink_nodes(child_id=child.id, parent_id=root.id)

        assert root.id not in child.parent_ids
        assert child.id not in root.child_ids


class TestMemoryGraphAncestors:
    """Test ancestor traversal."""

    def test_get_ancestors_empty(self):
        """Test getting ancestors of root (none)."""
        graph = MemoryGraph()
        root = graph.create_root_node()

        ancestors = graph.get_ancestors(root.id)

        assert len(ancestors) == 0

    def test_get_ancestors_single_parent(self):
        """Test getting ancestors with linear chain."""
        graph = MemoryGraph()
        root = graph.create_root_node()
        child = graph.create_node(parent_id=root.id)
        grandchild = graph.create_node(parent_id=child.id)

        ancestors = graph.get_ancestors(grandchild.id)

        assert len(ancestors) == 2
        ancestor_ids = [a.id for a in ancestors]
        assert child.id in ancestor_ids
        assert root.id in ancestor_ids

    def test_get_ancestors_multiple_parents(self):
        """Test getting ancestors with multiple parents (DAG)."""
        graph = MemoryGraph()
        root = graph.create_root_node()
        parent1 = graph.create_node(parent_id=root.id)
        parent2 = graph.create_node(parent_id=root.id)
        child = graph.create_node(parent_ids=[parent1.id, parent2.id])

        ancestors = graph.get_ancestors(child.id)

        assert len(ancestors) == 3  # parent1, parent2, root
        ancestor_ids = [a.id for a in ancestors]
        assert parent1.id in ancestor_ids
        assert parent2.id in ancestor_ids
        assert root.id in ancestor_ids


class TestMemoryGraphContext:
    """Test context building for LLM."""

    def test_context_from_root(self):
        """Test getting context from root node."""
        graph = MemoryGraph()
        root = graph.create_root_node()
        root.add_message(LLMMessage(role="user", content="Hello"))

        context = graph.get_context_for_llm(root.id)

        assert len(context) == 1
        assert context[0].content == "Hello"

    def test_context_includes_ancestor_summaries(self):
        """Test that context includes ancestor summaries."""
        graph = MemoryGraph()
        root = graph.create_root_node(metadata={"scope": "root"})
        root.set_summary("Root context summary")

        child = graph.create_node(parent_id=root.id)
        child.add_message(LLMMessage(role="user", content="Child message"))

        context = graph.get_context_for_llm(child.id)

        # Should have: 1 summary from root + 1 local message
        assert len(context) == 2
        assert "Root context summary" in context[0].content
        assert context[1].content == "Child message"

    def test_context_nonexistent_node(self):
        """Test getting context for nonexistent node."""
        graph = MemoryGraph()

        context = graph.get_context_for_llm("nonexistent")

        assert context == []


class TestMemoryGraphDeletion:
    """Test node deletion."""

    def test_delete_node(self):
        """Test deleting a node."""
        graph = MemoryGraph()
        root = graph.create_root_node()
        child = graph.create_node(parent_id=root.id)

        result = graph.delete_node(child.id)

        assert result is True
        assert graph.get_node(child.id) is None
        assert child.id not in root.child_ids

    def test_delete_root_clears_root_id(self):
        """Test that deleting root clears root_id."""
        graph = MemoryGraph()
        root = graph.create_root_node()

        graph.delete_node(root.id)

        assert graph.root_id is None

    def test_delete_nonexistent_node(self):
        """Test deleting nonexistent node returns False."""
        graph = MemoryGraph()

        result = graph.delete_node("nonexistent")

        assert result is False


class TestMemoryGraphSerialization:
    """Test graph serialization."""

    def test_serialization_roundtrip(self):
        """Test serializing and deserializing graph."""
        graph = MemoryGraph()
        root = graph.create_root_node(metadata={"scope": "root"})
        root.add_message(LLMMessage(role="user", content="Root message"))
        root.set_summary("Root summary")

        child = graph.create_node(parent_id=root.id, metadata={"scope": "child"})
        child.add_message(LLMMessage(role="assistant", content="Child response"))

        # Serialize
        data = graph.to_dict()

        # Deserialize
        restored = MemoryGraph.from_dict(data)

        assert restored.root_id == root.id
        assert len(restored.nodes) == 2

        restored_root = restored.get_node(root.id)
        assert restored_root.summary == "Root summary"
        assert restored_root.messages[0].content == "Root message"

        restored_child = restored.get_node(child.id)
        assert root.id in restored_child.parent_ids

    def test_get_stats(self):
        """Test getting graph statistics."""
        graph = MemoryGraph()
        root = graph.create_root_node()
        root.add_message(LLMMessage(role="user", content="Hello"))
        root.set_summary("Summary")

        child = graph.create_node(parent_id=root.id)
        child.add_message(LLMMessage(role="assistant", content="Hi"))

        stats = graph.get_stats()

        assert stats["node_count"] == 2
        assert stats["total_messages"] == 2
        assert stats["nodes_with_summary"] == 1
        assert stats["root_id"] == root.id


class TestMemoryGraphMerge:
    """Test node merging for parallel exploration results."""

    @pytest.mark.asyncio
    async def test_merge_nodes_without_llm(self):
        """Test merging nodes without LLM (summaries added directly)."""
        graph = MemoryGraph()  # No LLM
        root = graph.create_root_node()

        child1 = graph.create_node(parent_id=root.id, metadata={"scope": "explore1"})
        child1.set_summary("Exploration 1 findings")

        child2 = graph.create_node(parent_id=root.id, metadata={"scope": "explore2"})
        child2.set_summary("Exploration 2 findings")

        # Create merge target
        merge_target = graph.create_node(parent_id=root.id)

        await graph.merge_nodes(
            source_ids=[child1.id, child2.id],
            target_id=merge_target.id,
        )

        # Target should have merged context
        assert merge_target.message_count() == 1
        merged_content = merge_target.messages[0].content
        assert "Exploration 1 findings" in merged_content
        assert "Exploration 2 findings" in merged_content
