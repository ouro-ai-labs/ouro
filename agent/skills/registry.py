"""Skills registry implementation."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import aiofiles.os

from utils import terminal_ui

from .installer import (
    copy_tree,
    format_candidate_list,
    is_git_url,
    remove_tree,
)
from .parser import (
    list_skill_files,
    read_text,
    render_skill_prompt,
    split_frontmatter,
    split_invocation,
)
from .types import ResolvedInput, SkillInfo

# System skills are bundled with ouro
SYSTEM_SKILLS_DIR = Path(__file__).parent / "system"


class SkillsRegistry:
    """Index and resolve skills for ouro."""

    def __init__(self) -> None:
        self.skills: dict[str, SkillInfo] = {}

    async def load(self) -> None:
        skills_dir = Path.home() / ".ouro" / "skills"
        # Load user skills first, then system skills (user skills take precedence)
        self.skills = await self._load_skills(skills_dir)
        system_skills = await self._load_skills(SYSTEM_SKILLS_DIR)
        # Only add system skills that don't conflict with user skills
        for name, skill in system_skills.items():
            if name not in self.skills:
                self.skills[name] = skill

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

    async def load_skill_body(self, skill: SkillInfo) -> str:
        content = await read_text(skill.path / "SKILL.md")
        _, body = split_frontmatter(content)
        return body.strip()

    async def resolve_user_input(self, user_input: str) -> ResolvedInput:
        if user_input.startswith("$"):
            name, args = split_invocation(user_input, "$")
            skill = self.skills.get(name)
            if not skill:
                return ResolvedInput(user_input, user_input, None, args)
            body = await self.load_skill_body(skill)
            rendered = render_skill_prompt(skill.name, body, args)
            return ResolvedInput(user_input, rendered, skill.name, args)

        return ResolvedInput(user_input, user_input, None, "")

    async def install_skill(self, source: str) -> SkillInfo | None:
        source = source.strip()
        if not source:
            terminal_ui.print_error("Install source cannot be empty")
            return None

        if is_git_url(source):
            return await self._install_from_git(source)

        path = Path(source).expanduser().resolve()
        return await self._install_from_path(path)

    async def uninstall_skill(self, name: str) -> bool:
        name = name.strip()
        if not name:
            terminal_ui.print_error("Skill name cannot be empty")
            return False
        target_dir = Path.home() / ".ouro" / "skills" / name
        if not await aiofiles.os.path.exists(target_dir):
            terminal_ui.print_warning(f"Skill '{name}' not found in {target_dir}")
            return False
        await remove_tree(target_dir)
        return True

    async def _install_from_path(self, path: Path) -> SkillInfo | None:
        skill_file = path / "SKILL.md"
        if not await aiofiles.os.path.exists(skill_file):
            terminal_ui.print_error(f"SKILL.md not found at {skill_file}")
            return None

        content = await read_text(skill_file)
        frontmatter, _ = split_frontmatter(content)
        name = str(frontmatter.get("name", "")).strip()
        description = str(frontmatter.get("description", "")).strip()
        if not name or not description:
            terminal_ui.print_error("SKILL.md missing required name/description")
            return None

        dest_root = Path.home() / ".ouro" / "skills" / name
        if await aiofiles.os.path.exists(dest_root):
            terminal_ui.print_warning(f"Skill '{name}' already exists at {dest_root}")
            return None

        await aiofiles.os.makedirs(dest_root.parent, exist_ok=True)
        await copy_tree(path, dest_root)

        return SkillInfo(name=name, description=description, path=dest_root)

    async def _install_from_git(self, url: str) -> SkillInfo | None:
        subdir = None
        if "#" in url:
            url, _, subdir = url.partition("#")
            subdir = subdir.strip() or None

        def _mktemp() -> str:
            return tempfile.mkdtemp(prefix="ouro-skill-")

        temp_dir = Path(await asyncio.to_thread(_mktemp))
        try:
            try:
                result = await asyncio.create_subprocess_exec(
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    url,
                    str(temp_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError:
                terminal_ui.print_error("git is required to install from URL")
                return None
            stdout, stderr = await result.communicate()
            if result.returncode != 0:
                terminal_ui.print_error(
                    f"Git clone failed: {stderr.decode(errors='ignore').strip()}"
                )
                return None

            if subdir:
                candidate = temp_dir / subdir
                if not candidate.exists():
                    terminal_ui.print_error(f"Skill path not found: {candidate}")
                    return None
                return await self._install_from_path(candidate)

            candidates = await asyncio.to_thread(
                lambda: [p.parent for p in temp_dir.rglob("SKILL.md")]
            )
            if not candidates:
                terminal_ui.print_error("No SKILL.md found in repository")
                return None
            if len(candidates) > 1:
                terminal_ui.print_error(
                    "Multiple skills found. Specify one with '#<path>':\n"
                    f"{format_candidate_list(candidates)}"
                )
                return None
            return await self._install_from_path(candidates[0])
        finally:
            await remove_tree(temp_dir)
