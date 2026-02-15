"""Tests for LongTermMemoryManager facade."""

import pytest

from memory.long_term import LongTermMemoryManager
from memory.long_term.store import MemoryCategory


@pytest.mark.asyncio
class TestLongTermMemoryManager:
    async def test_load_and_format_empty(self, tmp_path, mock_ltm_llm):
        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        result = await manager.load_and_format()

        assert result is not None
        assert "<long_term_memory_management>" in result
        assert "</long_term_memory_management>" in result
        # No CURRENT MEMORIES section when everything is empty
        assert "CURRENT MEMORIES" not in result
        assert str(tmp_path / "mem") in result  # memory_dir injected

    async def test_load_and_format_with_entries(self, tmp_path, mock_ltm_llm, sample_memories):
        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        await manager.store.save_and_commit(sample_memories, "seed")

        result = await manager.load_and_format()
        assert "Use async-first architecture" in result
        assert "Prefer type hints everywhere" in result
        assert "Project uses Python 3.12+" in result

    async def test_load_and_format_triggers_consolidation(
        self, tmp_path, mock_ltm_llm, monkeypatch
    ):
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 1)

        mock_ltm_llm.response_text = (
            "## decisions\n- consolidated decision\n\n"
            "## preferences\n- consolidated pref\n\n"
            "## facts\n- consolidated fact\n"
        )

        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        big_memories = {
            MemoryCategory.DECISIONS: "\n".join(f"- decision {i}" for i in range(20)) + "\n",
            MemoryCategory.PREFERENCES: "\n".join(f"- pref {i}" for i in range(20)) + "\n",
            MemoryCategory.FACTS: "\n".join(f"- fact {i}" for i in range(20)) + "\n",
        }
        await manager.store.save_and_commit(big_memories, "seed")

        result = await manager.load_and_format()
        assert mock_ltm_llm.call_count == 1  # consolidation was triggered
        assert "consolidated decision" in result

    async def test_load_and_format_no_consolidation_below_threshold(
        self, tmp_path, mock_ltm_llm, monkeypatch
    ):
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 99999)

        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        await manager.load_and_format()
        assert mock_ltm_llm.call_count == 0

    async def test_has_changed_since_load(self, tmp_path, mock_ltm_llm, sample_memories):
        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        await manager.store.save_and_commit(sample_memories, "initial")
        await manager.load_and_format()

        assert not await manager.has_changed_since_load()

        # Simulate external change
        await manager.store.save_and_commit(
            {cat: "changed\n" for cat in MemoryCategory},
            "external",
        )
        assert await manager.has_changed_since_load()

    async def test_memory_dir_property(self, tmp_path, mock_ltm_llm):
        path = str(tmp_path / "mem")
        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=path)
        assert manager.memory_dir == path

    async def test_format_memories_skips_empty(self, tmp_path, mock_ltm_llm):
        """Empty categories should not appear in formatted output (save tokens)."""
        result = LongTermMemoryManager._format_memories(
            {
                MemoryCategory.DECISIONS: "- d1\n",
                MemoryCategory.PREFERENCES: "",
                MemoryCategory.FACTS: "- f1\n- f2\n",
            }
        )
        assert "[decisions]" in result
        assert "[facts]" in result
        assert "preferences" not in result  # empty, should be omitted
        assert "d1" in result
        assert "f2" in result
