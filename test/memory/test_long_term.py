"""Tests for long-term memory system."""

import pytest

from memory.long_term import Memory, MemoryIndexer


@pytest.fixture
async def indexer(tmp_path):
    """Create a MemoryIndexer instance with a temp directory."""
    memory_dir = str(tmp_path / "memory")
    idx = MemoryIndexer(memory_dir=memory_dir)
    return idx


class TestMemoryIndexer:
    """Tests for MemoryIndexer class."""

    async def test_save_creates_memory(self, indexer):
        """Test that save_memory creates a memory with correct fields."""
        saved = await indexer.save_memory("User prefers pytest", category="preference")

        assert saved.id is not None
        assert saved.content == "User prefers pytest"
        assert saved.category == "preference"
        assert saved.created_at is not None
        assert len(saved.keywords) > 0

    async def test_save_extracts_keywords(self, indexer):
        """Test that keywords are extracted from content."""
        saved = await indexer.save_memory(
            "User prefers pytest over unittest for testing Python code"
        )

        # Should extract meaningful keywords
        keywords_lower = [k.lower() for k in saved.keywords]
        assert "pytest" in keywords_lower
        assert "unittest" in keywords_lower
        assert "python" in keywords_lower

    async def test_save_filters_stop_words(self, indexer):
        """Test that stop words are filtered from keywords."""
        saved = await indexer.save_memory("The user is a developer who likes to code")

        keywords_lower = [k.lower() for k in saved.keywords]
        # Stop words should be filtered
        assert "the" not in keywords_lower
        assert "is" not in keywords_lower
        assert "to" not in keywords_lower
        # Meaningful words should be kept
        assert "user" in keywords_lower
        assert "developer" in keywords_lower

    async def test_save_persists_to_file(self, indexer, tmp_path):
        """Test that memories are persisted to YAML file."""
        await indexer.save_memory("Test memory content", category="fact")

        # Check file exists
        memory_file = tmp_path / "memory" / "memories.yaml"
        assert memory_file.exists()

        # Check content
        content = memory_file.read_text()
        assert "Test memory content" in content
        assert "category: fact" in content

    async def test_search_returns_relevant_results(self, indexer):
        """Test that search returns relevant memories using keyword fallback."""
        await indexer.save_memory("User prefers pytest for testing", category="preference")
        await indexer.save_memory("Project uses black for formatting", category="fact")
        await indexer.save_memory("Always use type hints in Python", category="preference")

        # Keyword search (no embedding configured)
        results = await indexer.search("pytest testing")

        assert len(results) > 0
        # First result should be about pytest
        assert "pytest" in results[0].content.lower()

    async def test_search_filters_by_category(self, indexer):
        """Test that search can filter by category."""
        await indexer.save_memory("User prefers pytest", category="preference")
        await indexer.save_memory("Project uses pytest", category="fact")

        results = await indexer.search("pytest", category="preference")

        assert len(results) == 1
        assert results[0].category == "preference"

    async def test_search_filters_by_source(self, indexer):
        """Test that search can filter by source."""
        await indexer.save_memory("User prefers pytest", category="preference")

        results = await indexer.search("pytest", source="memories")

        assert len(results) >= 1
        assert all(r.source == "memories" for r in results)

    async def test_search_respects_limit(self, indexer):
        """Test that search respects the limit parameter."""
        for i in range(10):
            await indexer.save_memory(f"Memory about Python topic {i}", category="fact")

        results = await indexer.search("Python", limit=3)

        assert len(results) <= 3

    async def test_list_all_returns_all_memories(self, indexer):
        """Test that list_memories returns all stored memories."""
        await indexer.save_memory("Memory 1", category="decision")
        await indexer.save_memory("Memory 2", category="fact")
        await indexer.save_memory("Memory 3", category="decision")

        all_memories = await indexer.list_memories()

        assert len(all_memories) == 3

    async def test_list_all_filters_by_category(self, indexer):
        """Test that list_memories can filter by category."""
        await indexer.save_memory("Memory 1", category="decision")
        await indexer.save_memory("Memory 2", category="fact")
        await indexer.save_memory("Memory 3", category="decision")

        filtered = await indexer.list_memories(category="decision")

        assert len(filtered) == 2
        assert all(m.category == "decision" for m in filtered)

    async def test_delete_removes_memory(self, indexer):
        """Test that delete_memory removes a memory by ID."""
        saved = await indexer.save_memory("To be deleted", category="fact")
        memory_id = saved.id

        result = await indexer.delete_memory(memory_id)

        assert result is True
        all_memories = await indexer.list_memories()
        assert len(all_memories) == 0

    async def test_delete_returns_false_for_unknown_id(self, indexer):
        """Test that delete_memory returns False for non-existent ID."""
        result = await indexer.delete_memory("nonexistent")

        assert result is False

    async def test_clear_removes_all_memories(self, indexer):
        """Test that clear_memories removes all memories."""
        await indexer.save_memory("Memory 1")
        await indexer.save_memory("Memory 2")
        await indexer.save_memory("Memory 3")

        deleted = await indexer.clear_memories()

        assert deleted == 3
        all_memories = await indexer.list_memories()
        assert len(all_memories) == 0

    async def test_clear_by_category(self, indexer):
        """Test that clear_memories can target a specific category."""
        await indexer.save_memory("Memory 1", category="preference")
        await indexer.save_memory("Memory 2", category="fact")
        await indexer.save_memory("Memory 3", category="fact")

        deleted = await indexer.clear_memories(category="fact")

        assert deleted == 2
        remaining = await indexer.list_memories()
        assert len(remaining) == 1
        assert remaining[0].category == "preference"

    async def test_persistence_across_instances(self, tmp_path):
        """Test that memories persist across different instances."""
        memory_dir = str(tmp_path / "memory")

        # Save with first instance
        idx1 = MemoryIndexer(memory_dir=memory_dir)
        await idx1.save_memory("Persistent memory", category="fact")

        # Load with new instance
        idx2 = MemoryIndexer(memory_dir=memory_dir)
        results = await idx2.search("Persistent")

        assert len(results) == 1
        assert results[0].content == "Persistent memory"

    async def test_keyword_extraction_limits(self, indexer):
        """Test that keyword extraction is limited to prevent excessive keywords."""
        # Create content with many words
        long_content = " ".join([f"word{i}" for i in range(100)])
        saved = await indexer.save_memory(long_content)

        # Keywords should be limited (to 10)
        assert len(saved.keywords) <= 10

    async def test_valid_categories(self, indexer):
        """Test that only valid categories are accepted."""
        # Valid categories
        for cat in ["decision", "preference", "fact"]:
            saved = await indexer.save_memory(f"Memory with {cat}", category=cat)
            assert saved.category == cat

        # Invalid category defaults to 'fact'
        saved = await indexer.save_memory("Invalid category", category="invalid")
        assert saved.category == "fact"


class TestKeywordSearch:
    """Tests for keyword-based search (fallback when embeddings not configured)."""

    async def test_exact_match_in_content(self, indexer):
        """Test that exact substring matches are found."""
        await indexer.save_memory("pytest is the best testing framework", category="fact")
        await indexer.save_memory("testing code is important", category="fact")

        results = await indexer.search("pytest")

        assert len(results) >= 1
        assert "pytest" in results[0].content.lower()

    async def test_keyword_overlap_scoring(self, indexer):
        """Test that keyword overlap affects scoring."""
        await indexer.save_memory("Python testing with pytest framework", category="fact")
        await indexer.save_memory("General programming tips", category="fact")

        results = await indexer.search("python pytest testing")

        # First result should have better keyword overlap
        assert len(results) >= 1
        assert "pytest" in results[0].content.lower() or "python" in results[0].content.lower()


class TestMemoryDataClass:
    """Tests for the Memory data class."""

    def test_memory_fields(self):
        """Test Memory dataclass has expected fields."""
        mem = Memory(
            id="test123",
            content="Test content",
            category="fact",
            created_at="2024-01-01T00:00:00",
            source="memories",
            keywords=["test", "content"],
        )

        assert mem.id == "test123"
        assert mem.content == "Test content"
        assert mem.category == "fact"
        assert mem.source == "memories"
        assert mem.keywords == ["test", "content"]
