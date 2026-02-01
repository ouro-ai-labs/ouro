import textwrap

import pytest

from utils.skills import SkillsRegistry


@pytest.mark.asyncio
async def test_skills_registry_load_and_resolve(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    skills_root = tmp_path / ".aloop" / "skills" / "code-review"
    skills_root.mkdir(parents=True)
    (skills_root / "SKILL.md").write_text(
        textwrap.dedent(
            """
            ---
            name: code-review
            description: Review code for correctness.
            ---

            Always review carefully.
            """
        ).strip()
    )

    repo_root = tmp_path / "repo"
    commands_dir = repo_root / ".aloop" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "review.md").write_text(
        textwrap.dedent(
            """
            ---
            description: Perform review.
            requires-skills:
              - code-review
            ---

            Please review: $ARGUMENTS
            """
        ).strip()
    )

    monkeypatch.chdir(repo_root)

    registry = SkillsRegistry()
    await registry.load()

    resolved = await registry.resolve_user_input("/review fix bug")
    assert "SKILL: code-review" in resolved.rendered
    assert "Always review carefully." in resolved.rendered
    assert "Please review: fix bug" in resolved.rendered


@pytest.mark.asyncio
async def test_skills_registry_skill_invocation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    skills_root = tmp_path / ".aloop" / "skills" / "lint"
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
