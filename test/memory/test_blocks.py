"""Unit tests for MemoryBlockManager."""

import pytest

from ouro.capabilities.memory.blocks import (
    BlockBudgetExceeded,
    MemoryBlockManager,
)


@pytest.fixture
def manager(tmp_path):
    # No LLM → token counter falls back to len(text)//3 heuristic.
    # Use tight budgets so we can probe overflow without writing huge strings.
    return MemoryBlockManager(
        llm=None,
        memory_dir=str(tmp_path),
        block_budgets={"user": 20, "project": 40, "scratch": 60},
    )


class TestEmpty:
    async def test_missing_block_reads_as_empty(self, manager):
        assert await manager.read("user") == ""

    async def test_load_and_format_when_all_empty(self, manager):
        out = await manager.load_and_format()
        assert out is not None
        assert "all blocks are currently empty" in out
        assert "user — 20" in out
        assert "<long_term_memory>" in out


class TestStrictReplace:
    async def test_full_overwrite(self, manager):
        b = await manager.replace("user", "", "name: alice")
        assert b.content == "name: alice"
        assert (await manager.read("user")) == "name: alice"

    async def test_targeted_replace(self, manager):
        await manager.replace("user", "", "rust >> go")
        b = await manager.replace("user", "rust", "RUST")
        assert "RUST >> go" in b.content

    async def test_targeted_replace_missing_substring(self, manager):
        await manager.replace("user", "", "hello")
        with pytest.raises(ValueError, match="not found verbatim"):
            await manager.replace("user", "nope", "world")

    async def test_overflow_raises(self, manager):
        big = "x" * 200  # ~66 tokens via fallback heuristic, budget=20
        with pytest.raises(BlockBudgetExceeded) as exc:
            await manager.replace("user", "", big)
        assert exc.value.block == "user"
        assert exc.value.budget == 20

    async def test_overflow_does_not_partially_write(self, manager):
        await manager.replace("user", "", "keep me")
        with pytest.raises(BlockBudgetExceeded):
            await manager.replace("user", "", "x" * 500)
        # Disk state must still be the previous good value.
        assert (await manager.read("user")) == "keep me"


class TestStrictAppend:
    async def test_basic_append(self, manager):
        await manager.append("project", "first line")
        await manager.append("project", "second line")
        body = await manager.read("project")
        assert "first line" in body
        assert "second line" in body

    async def test_append_overflow_raises(self, manager):
        # project budget=40. Fill to ~30, then try to append another ~30.
        await manager.append("project", "a" * 60)  # ~20 tokens
        await manager.append("project", "b" * 30)  # ~10 more → ~30 total (separator counted)
        with pytest.raises(BlockBudgetExceeded):
            await manager.append("project", "c" * 200)


class TestLenientScratch:
    async def test_overflow_fifo_truncates_oldest(self, manager):
        # Each paragraph is ~10 tokens, budget=60 → ~6 paragraphs fit.
        for i in range(10):
            await manager.append("scratch", f"para-{i}: " + "x" * 20)
        body = await manager.read("scratch")
        # Oldest paragraphs should have been dropped; newest must survive.
        assert "para-9" in body
        assert "para-0" not in body

    async def test_oversized_single_addition_truncates_head(self, manager):
        huge = "\n".join(f"line-{i}" for i in range(50))
        await manager.append("scratch", huge)
        body = await manager.read("scratch")
        assert "line-49" in body  # tail preserved
        # Head dropped due to head-truncation fallback.
        assert "line-0\n" not in body or len(body) < len(huge)

    async def test_append_scratch_never_raises(self, manager):
        # The compaction-time helper must swallow all errors.
        await manager.append_scratch("x" * 10_000)  # well over budget
        # No assertion needed; absence of exception is the assertion.

    async def test_read_scratch(self, manager):
        await manager.append("scratch", "hello world")
        assert "hello world" in await manager.read_scratch()


class TestLoadAndFormat:
    async def test_renders_block_contents(self, manager):
        await manager.replace("user", "", "name: alice")
        await manager.append("scratch", "decided on rust")
        out = await manager.load_and_format()
        assert "--- user ---" in out
        assert "name: alice" in out
        assert "--- scratch ---" in out
        assert "decided on rust" in out

    async def test_stats(self, manager):
        await manager.replace("user", "", "abc")
        stats = await manager.stats()
        assert "user" in stats
        assert "project" in stats
        assert "scratch" in stats
        assert stats["user"]["tokens"] > 0
        assert stats["user"]["budget"] == 20
        assert stats["user"]["full_pct"] >= 0
