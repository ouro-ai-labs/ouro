"""Tests for the default ouro system prompt."""

from ouro.capabilities.prompts import DEFAULT_SYSTEM_PROMPT


def test_default_system_prompt_is_judgement_oriented() -> None:
    """The base prompt should guide judgement without over-prescribing loops."""
    assert "Use judgement rather than rigid procedure" in DEFAULT_SYSTEM_PROMPT
    assert "Use progressive disclosure" in DEFAULT_SYSTEM_PROMPT
    assert "Tool interfaces and descriptions are the source of truth" in DEFAULT_SYSTEM_PROMPT

    # Detailed tool selection rules belong in tool descriptions, not the base prompt.
    assert "For each user request, follow this ReAct pattern" not in DEFAULT_SYSTEM_PROMPT
    assert "Use bash for file operations" not in DEFAULT_SYSTEM_PROMPT
    assert "Use grep_content for text/code search" not in DEFAULT_SYSTEM_PROMPT


def test_default_system_prompt_keeps_code_style_guidance_general() -> None:
    """Code-writing guidance should match the local project instead of fixed rules."""
    assert "match the surrounding project's style" in DEFAULT_SYSTEM_PROMPT
    assert "comment density" in DEFAULT_SYSTEM_PROMPT
    assert "Prefer small, reviewable changes" in DEFAULT_SYSTEM_PROMPT
