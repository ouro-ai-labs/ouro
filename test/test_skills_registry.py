import textwrap

import pytest

from agent.skills import SkillsRegistry
from agent.skills.registry import BUNDLED_SKILLS_DIR


@pytest.mark.asyncio
async def test_bundled_skills_bootstrapped(tmp_path, monkeypatch) -> None:
    """Test that bundled skills are bootstrapped to ~/.ouro/skills/."""
    monkeypatch.setenv("HOME", str(tmp_path))

    # Create empty user skills directory
    (tmp_path / ".ouro" / "skills").mkdir(parents=True)

    registry = SkillsRegistry()
    await registry.load()

    # Bundled skills should be bootstrapped and loaded
    assert "skill-creator" in registry.skills
    assert "skill-installer" in registry.skills

    # Check they have proper descriptions
    assert "creating" in registry.skills["skill-creator"].description.lower()
    assert "install" in registry.skills["skill-installer"].description.lower()

    # They should live under ~/.ouro/skills/, not the system dir
    for skill in registry.skills.values():
        assert str(tmp_path / ".ouro" / "skills") in str(skill.path)


@pytest.mark.asyncio
async def test_user_skill_overrides_system_skill(tmp_path, monkeypatch) -> None:
    """Test that user skills take precedence over bundled skills (bootstrap skips existing)."""
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


@pytest.mark.asyncio
async def test_call_skill(tmp_path, monkeypatch) -> None:
    """Test call_skill returns lightweight prompt for known skill, None for unknown."""
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

    # Known skill with args
    rendered = registry.call_skill("lint", "src/")
    assert rendered is not None
    assert "lint" in rendered
    assert "src/" in rendered
    # Should NOT contain the full body (progressive disclosure)
    assert "Run lint and report issues." not in rendered

    # Without args
    rendered_no_args = registry.call_skill("lint")
    assert rendered_no_args is not None
    assert "lint" in rendered_no_args
    assert "Arguments" not in rendered_no_args

    # Unknown skill
    result = registry.call_skill("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_install_dynamic_reload(tmp_path, monkeypatch) -> None:
    """Test that install_skill adds to registry immediately."""
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".ouro" / "skills").mkdir(parents=True)

    # Create a skill source to install
    source = tmp_path / "my-skill"
    source.mkdir()
    (source / "SKILL.md").write_text(
        textwrap.dedent(
            """
            ---
            name: my-skill
            description: A test skill.
            ---

            Test skill body.
            """
        ).strip()
    )

    registry = SkillsRegistry()
    await registry.load()

    assert "my-skill" not in registry.skills

    result = await registry.install_skill(str(source))
    assert result is not None
    assert result.name == "my-skill"
    # Should be in registry immediately
    assert "my-skill" in registry.skills


@pytest.mark.asyncio
async def test_uninstall_dynamic_reload(tmp_path, monkeypatch) -> None:
    """Test that uninstall_skill removes from registry immediately."""
    monkeypatch.setenv("HOME", str(tmp_path))
    skills_root = tmp_path / ".ouro" / "skills" / "removeme"
    skills_root.mkdir(parents=True)
    (skills_root / "SKILL.md").write_text(
        textwrap.dedent(
            """
            ---
            name: removeme
            description: Will be removed.
            ---

            Body.
            """
        ).strip()
    )

    registry = SkillsRegistry()
    await registry.load()

    assert "removeme" in registry.skills

    ok = await registry.uninstall_skill("removeme")
    assert ok
    # Should be gone from registry immediately
    assert "removeme" not in registry.skills


def test_bundled_skills_dir_exists() -> None:
    """Test that the bundled skills directory exists and contains expected skills."""
    assert BUNDLED_SKILLS_DIR.exists()
    assert (BUNDLED_SKILLS_DIR / "skill-creator" / "SKILL.md").exists()
    assert (BUNDLED_SKILLS_DIR / "skill-installer" / "SKILL.md").exists()
