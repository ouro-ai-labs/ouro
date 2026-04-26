"""Skills registry implementation."""

from __future__ import annotations

from pathlib import Path

import aiofiles.os

from utils import terminal_ui

from .installer import copy_tree
from .parser import (
    list_skill_files,
    read_text,
    split_frontmatter,
)
from .types import SkillInfo

# Bundled skills shipped with ouro (source for seeding only)
BUNDLED_SKILLS_DIR = Path(__file__).parent / "system"


class SkillsRegistry:
    """Index and resolve skills for ouro."""

    def __init__(self, skills_dir: Path | None = None, *, bootstrap: bool = False) -> None:
        self.skills: dict[str, SkillInfo] = {}
        self._skills_dir = skills_dir or (Path.home() / ".ouro" / "skills")
        self._bootstrap = bootstrap

    async def load(self) -> None:
        if self._bootstrap:
            await self._bootstrap_bundled_skills()
        self.skills = await self._load_skills(self._skills_dir)

    async def _bootstrap_bundled_skills(self) -> None:
        """Copy bundled skills to the skills directory if not already present."""
        if not await aiofiles.os.path.exists(BUNDLED_SKILLS_DIR):
            return
        for skill_file in await list_skill_files(BUNDLED_SKILLS_DIR):
            skill_dir = skill_file.parent
            name = skill_dir.name
            dest = self._skills_dir / name
            if await aiofiles.os.path.exists(dest):
                continue  # User already has this skill — don't overwrite
            await aiofiles.os.makedirs(dest.parent, exist_ok=True)
            await copy_tree(skill_dir, dest)

    async def _load_skills(self, skills_dir: Path) -> dict[str, SkillInfo]:
        results: dict[str, SkillInfo] = {}
        for skill_file in await list_skill_files(skills_dir):
            content = await read_text(skill_file)
            frontmatter, _ = split_frontmatter(content)
            name = str(frontmatter.get("name", "")).strip()
            description = str(frontmatter.get("description", "")).strip()
            if not name or not description:
                terminal_ui.print_warning(f"Skipping skill without required fields: {skill_file}")
                continue
            results[name] = SkillInfo(
                name=name,
                description=description,
                path=skill_file.parent,
            )
        return results

    def call_skill(self, name: str, args: str = "") -> str | None:
        """Build a lightweight prompt for explicit skill invocation.

        Does NOT read the skill body — the LLM will open the SKILL.md
        itself via progressive disclosure (read_file tool).

        Args:
            name: Skill name to invoke.
            args: Optional arguments string.

        Returns:
            Short prompt string, or None if skill not found.
        """
        skill = self.skills.get(name)
        if not skill:
            return None
        prompt = f"Use skill '{skill.name}'."
        if args:
            prompt += f" Arguments: {args}"
        return prompt
