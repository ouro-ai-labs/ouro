"""Tests for LongTermMemoryConsolidator."""

from datetime import date

import pytest

from memory.long_term.consolidator import LongTermMemoryConsolidator


@pytest.mark.asyncio
class TestConsolidator:
    async def test_should_consolidate_below_threshold(self, mock_ltm_llm, monkeypatch):
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 5000)
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        assert not consolidator.should_consolidate("short")

    async def test_should_consolidate_above_threshold(self, mock_ltm_llm, monkeypatch):
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 10)
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        assert consolidator.should_consolidate("a" * 200)

    async def test_should_consolidate_combined_contents(self, mock_ltm_llm, monkeypatch):
        """Combined size of multiple contents is checked against threshold."""
        from config import Config

        monkeypatch.setattr(Config, "LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD", 10)
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        # Each part alone might be small, but together they exceed
        assert consolidator.should_consolidate("a" * 100, "b" * 100)

    async def test_consolidate_returns_llm_output(self, mock_ltm_llm):
        mock_ltm_llm.response_text = "- consolidated decision\n- consolidated pref\n"
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        result = await consolidator.consolidate("- d1\n- d2\n- p1\n")
        assert "consolidated decision" in result
        assert mock_ltm_llm.call_count == 1

    async def test_consolidate_falls_back_on_empty(self, mock_ltm_llm):
        mock_ltm_llm.response_text = ""
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        original = "- keep me\n"
        result = await consolidator.consolidate(original)
        assert result == original

    async def test_estimate_tokens_fallback(self, mock_ltm_llm):
        """Fallback to char-ratio when litellm is unavailable for the model."""
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        # With mock model, litellm may fall back to char ratio
        tokens = consolidator._estimate_tokens("hello world")
        assert tokens > 0


@pytest.mark.asyncio
class TestPromoteFromDailies:
    async def test_promote_returns_llm_output(self, mock_ltm_llm):
        mock_ltm_llm.response_text = "## Decisions\n- Use async-first\n\n## Facts\n- Python 3.12+\n"
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        dailies = [(date(2026, 2, 23), "- User prefers dark theme\n- Python 3.12+\n")]

        result = await consolidator.promote_from_dailies(
            "## Decisions\n- Use async-first\n", dailies
        )
        assert result is not None
        assert "Python 3.12+" in result
        assert mock_ltm_llm.call_count == 1

    async def test_promote_returns_none_on_empty_dailies(self, mock_ltm_llm):
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        result = await consolidator.promote_from_dailies("existing", [])
        assert result is None
        assert mock_ltm_llm.call_count == 0

    async def test_promote_returns_none_on_empty_response(self, mock_ltm_llm):
        mock_ltm_llm.response_text = ""
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        dailies = [(date(2026, 2, 23), "- some note\n")]

        result = await consolidator.promote_from_dailies("existing", dailies)
        assert result is None

    async def test_promote_formats_dailies_with_dates(self, mock_ltm_llm):
        mock_ltm_llm.response_text = "updated permanent"
        consolidator = LongTermMemoryConsolidator(mock_ltm_llm)
        dailies = [
            (date(2026, 2, 22), "- note A"),
            (date(2026, 2, 23), "- note B"),
        ]

        await consolidator.promote_from_dailies("permanent", dailies)
        # Check that the prompt included date-labelled daily sections
        last_msg = mock_ltm_llm.last_messages[0]
        prompt_text = last_msg.content if isinstance(last_msg.content, str) else ""
        assert "2026-02-22" in prompt_text
        assert "2026-02-23" in prompt_text
        assert "note A" in prompt_text
        assert "note B" in prompt_text
