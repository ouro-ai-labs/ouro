"""Tests for render_skills_section."""

from pathlib import Path

from agent.skills import SkillInfo, render_skills_section


def test_render_skills_section_empty() -> None:
    """Empty skills list returns None."""
    result = render_skills_section([])
    assert result is None


def test_render_skills_section_single() -> None:
    """Single skill is rendered correctly."""
    skills = [
        SkillInfo(
            name="code-review",
            description="Review code for style and correctness.",
            path=Path("/home/user/.ouro/skills/code-review"),
        )
    ]
    result = render_skills_section(skills)

    assert result is not None
    assert "## Skills" in result
    assert "### Available skills" in result
    assert "- code-review: Review code for style and correctness." in result
    assert "/home/user/.ouro/skills/code-review/SKILL.md" in result
    assert "### How to use skills" in result
    assert "Trigger rules:" in result


def test_render_skills_section_multiple_sorted() -> None:
    """Multiple skills are sorted alphabetically."""
    skills = [
        SkillInfo(
            name="zed-tool",
            description="Z comes last.",
            path=Path("/skills/zed-tool"),
        ),
        SkillInfo(
            name="alpha-tool",
            description="A comes first.",
            path=Path("/skills/alpha-tool"),
        ),
    ]
    result = render_skills_section(skills)

    assert result is not None
    # Check that alpha comes before zed in the output
    alpha_pos = result.find("alpha-tool")
    zed_pos = result.find("zed-tool")
    assert alpha_pos < zed_pos, "Skills should be sorted alphabetically"
