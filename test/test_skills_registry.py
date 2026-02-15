import textwrap

import pytest

from agent.skills import SYSTEM_SKILLS_DIR, SkillsRegistry


@pytest.mark.asyncio
async def test_skills_registry_unknown_slash_is_passthrough(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    skills_root = tmp_path / ".ouro" / "skills" / "lint"
    skills_root.mkdir(parents=True)
    (skills_root / "SKILL.md").write_text(
        textwrap.dedent(
            """
            ---
            name: lint
            description: Run lint checks.
            ---

            Run lint and report issues.
            """
        ).strip()
    )

    registry = SkillsRegistry()
    await registry.load()

    resolved = await registry.resolve_user_input("/review fix bug")
    assert resolved.rendered == "/review fix bug"
    assert resolved.invoked_skill is None


@pytest.mark.asyncio
async def test_skills_registry_skill_invocation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    skills_root = tmp_path / ".ouro" / "skills" / "lint"
    skills_root.mkdir(parents=True)
    (skills_root / "SKILL.md").write_text(
        textwrap.dedent(
            """
            ---
            name: lint
            description: Run lint checks.
            ---

            Run lint and report issues.
            """
        ).strip()
    )

    registry = SkillsRegistry()
    await registry.load()

    resolved = await registry.resolve_user_input("$lint src/")
    assert "SKILL: lint" in resolved.rendered
    assert "Run lint and report issues." in resolved.rendered
    assert "ARGUMENTS: src/" in resolved.rendered


@pytest.mark.asyncio
async def test_system_skills_loaded(tmp_path, monkeypatch) -> None:
    """Test that system skills (skill-creator, skill-installer) are loaded."""
    monkeypatch.setenv("HOME", str(tmp_path))

    # Create empty user skills directory
    (tmp_path / ".ouro" / "skills").mkdir(parents=True)

    registry = SkillsRegistry()
    await registry.load()

    # System skills should be loaded
    assert "skill-creator" in registry.skills
    assert "skill-installer" in registry.skills

    # Check they have proper descriptions
    assert "creating" in registry.skills["skill-creator"].description.lower()
    assert "install" in registry.skills["skill-installer"].description.lower()


@pytest.mark.asyncio
async def test_user_skill_overrides_system_skill(tmp_path, monkeypatch) -> None:
    """Test that user skills take precedence over system skills."""
    monkeypatch.setenv("HOME", str(tmp_path))

    # Create a user skill with same name as system skill
    user_skill = tmp_path / ".ouro" / "skills" / "skill-creator"
    user_skill.mkdir(parents=True)
    (user_skill / "SKILL.md").write_text(
        textwrap.dedent(
            """
            ---
            name: skill-creator
            description: Custom user version of skill-creator.
            ---

            My custom skill creator.
            """
        ).strip()
    )

    registry = SkillsRegistry()
    await registry.load()

    # User skill should take precedence
    assert "skill-creator" in registry.skills
    assert "custom" in registry.skills["skill-creator"].description.lower()


def test_system_skills_dir_exists() -> None:
    """Test that the system skills directory exists and contains expected skills."""
    assert SYSTEM_SKILLS_DIR.exists()
    assert (SYSTEM_SKILLS_DIR / "skill-creator" / "SKILL.md").exists()
    assert (SYSTEM_SKILLS_DIR / "skill-installer" / "SKILL.md").exists()
