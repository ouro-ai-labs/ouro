"""Tests for GitMemoryStore."""

import pytest

from memory.long_term.store import GitMemoryStore, MemoryCategory


@pytest.mark.asyncio
class TestGitMemoryStore:
    async def test_ensure_repo_creates_git_dir(self, tmp_path):
        store = GitMemoryStore(memory_dir=str(tmp_path / "mem"))
        await store.ensure_repo()
        assert (tmp_path / "mem" / ".git").is_dir()

    async def test_ensure_repo_idempotent(self, tmp_path):
        store = GitMemoryStore(memory_dir=str(tmp_path / "mem"))
        await store.ensure_repo()
        await store.ensure_repo()  # should not raise
        assert (tmp_path / "mem" / ".git").is_dir()

    async def test_load_all_empty(self, git_store):
        memories = await git_store.load_all()
        for cat in MemoryCategory:
            assert memories[cat] == ""

    async def test_save_and_load_roundtrip(self, git_store, sample_memories):
        await git_store.save_and_commit(sample_memories, "test commit")
        loaded = await git_store.load_all()
        for cat in MemoryCategory:
            assert loaded[cat] == sample_memories[cat]

    async def test_head_detection_no_commits(self, tmp_path):
        store = GitMemoryStore(memory_dir=str(tmp_path / "mem"))
        await store.ensure_repo()
        head = await store.get_current_head()
        assert head is None

    async def test_head_detection_after_commit(self, git_store, sample_memories):
        await git_store.save_and_commit(sample_memories, "first commit")
        head = await git_store.get_current_head()
        assert head is not None
        assert len(head) == 40  # SHA-1 hex

    async def test_has_changed_since_load_false(self, git_store, sample_memories):
        await git_store.save_and_commit(sample_memories, "initial")
        await git_store.load_all()  # snapshots HEAD
        assert not await git_store.has_changed_since_load()

    async def test_has_changed_since_load_true(self, git_store, sample_memories):
        await git_store.save_and_commit(sample_memories, "initial")
        await git_store.load_all()  # snapshots HEAD

        # Simulate another agent committing
        updated = {
            MemoryCategory.DECISIONS: "- new decision\n",
            MemoryCategory.PREFERENCES: "",
            MemoryCategory.FACTS: "",
        }
        await git_store.save_and_commit(updated, "external change")
        assert await git_store.has_changed_since_load()

    async def test_save_no_changes_skips_commit(self, git_store, sample_memories):
        await git_store.save_and_commit(sample_memories, "first")
        head_before = await git_store.get_current_head()

        # Save identical content — should not create a new commit
        await git_store.save_and_commit(sample_memories, "duplicate")
        head_after = await git_store.get_current_head()
        assert head_before == head_after

    async def test_read_nonexistent_file(self, git_store):
        """Missing files should return empty string."""
        memories = await git_store.load_all()
        assert memories[MemoryCategory.DECISIONS] == ""

    async def test_read_arbitrary_content(self, git_store):
        """Store preserves arbitrary markdown content."""
        content = "# My Decisions\n\nWe chose React for the frontend.\n"
        memories = {
            MemoryCategory.DECISIONS: content,
            MemoryCategory.PREFERENCES: "",
            MemoryCategory.FACTS: "",
        }
        await git_store.save_and_commit(memories, "test")
        loaded = await git_store.load_all()
        assert loaded[MemoryCategory.DECISIONS] == content
