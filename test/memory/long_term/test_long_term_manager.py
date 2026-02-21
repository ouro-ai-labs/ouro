"""Tests for LongTermMemoryManager facade."""

import pytest

from memory.long_term import LongTermMemoryManager


@pytest.mark.asyncio
class TestLongTermMemoryManager:
    async def test_load_and_format_empty(self, tmp_path, mock_ltm_llm):
        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        result = await manager.load_and_format()

        assert result is not None
        assert "<long_term_memory>" in result
        assert "</long_term_memory>" in result
        # No CURRENT MEMORIES section when everything is empty
        assert "CURRENT MEMORIES" not in result
        assert str(tmp_path / "mem") in result  # memory_dir injected

    async def test_load_and_format_with_entries(self, tmp_path, mock_ltm_llm, sample_content):
        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        await manager.store.save(sample_content)

        result = await manager.load_and_format()
        assert "Use async-first architecture" in result
        assert "Prefer type hints everywhere" in result
        assert "Project uses Python 3.12+" in result

    async def test_load_and_format_triggers_consolidation(
        self, tmp_path, mock_ltm_llm, monkeypatch
    ):
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 1)

        mock_ltm_llm.response_text = "- consolidated decision\n- consolidated pref\n"

        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=str(tmp_path / "mem"))
        big_content = "\n".join(f"- item {i}" for i in range(60)) + "\n"
        await manager.store.save(big_content)

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

    async def test_memory_dir_property(self, tmp_path, mock_ltm_llm):
        path = str(tmp_path / "mem")
        manager = LongTermMemoryManager(mock_ltm_llm, memory_dir=path)
        assert manager.memory_dir == path

    async def test_format_memories_empty(self, tmp_path, mock_ltm_llm):
        """Empty content should produce no CURRENT MEMORIES section."""
        result = LongTermMemoryManager._format_memories("")
        assert result == ""

    async def test_format_memories_nonempty(self, tmp_path, mock_ltm_llm):
        """Non-empty content should be wrapped in CURRENT MEMORIES."""
        result = LongTermMemoryManager._format_memories("- d1\n- f1\n")
        assert "CURRENT MEMORIES" in result
        assert "d1" in result
        assert "f1" in result
