"""Skills system utilities for aloop (MVP)."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import aiofiles
import aiofiles.os
import yaml

from utils import terminal_ui


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    path: Path


@dataclass(frozen=True)
class CommandInfo:
    name: str
    description: str
    path: Path
    requires_skills: list[str]
    template: str


@dataclass(frozen=True)
class ResolvedInput:
    original: str
    rendered: str
    invoked_command: str | None
    invoked_skill: str | None
    arguments: str


_GIT_URL_RE = re.compile(r"^(https?://|git@|ssh://)")


def _is_git_url(value: str) -> bool:
    return bool(_GIT_URL_RE.match(value)) or value.endswith(".git")


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, text

    yaml_text = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])

    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        return {}, text

    if not isinstance(data, dict):
        return {}, body

    return data, body


def _split_invocation(value: str, prefix: str) -> tuple[str, str]:
    stripped = value[len(prefix) :].strip()
    name, _, rest = stripped.partition(" ")
    return name.strip(), rest.strip()


def _render_template(template: str, arguments: str) -> str:
    if "$ARGUMENTS" in template:
        return template.replace("$ARGUMENTS", arguments)
    if not arguments:
        return template
    suffix = f"\n\nARGUMENTS: {arguments}" if template.strip() else f"ARGUMENTS: {arguments}"
    return f"{template.rstrip()}{suffix}"


def _render_skill_prompt(name: str, body: str, arguments: str) -> str:
    parts = [f"SKILL: {name}", body.strip()]
    if arguments:
        parts.append(f"ARGUMENTS: {arguments}")
    return "\n\n".join(part for part in parts if part)


async def _read_text(path: Path) -> str:
    async with aiofiles.open(path, encoding="utf-8") as handle:
        return await handle.read()


async def _list_command_files(commands_dir: Path) -> list[Path]:
    if not await aiofiles.os.path.exists(commands_dir):
        return []

    def _collect() -> list[Path]:
        return [p for p in commands_dir.glob("*.md") if p.is_file()]

    return await asyncio.to_thread(_collect)


async def _list_skill_files(skills_dir: Path) -> list[Path]:
    if not await aiofiles.os.path.exists(skills_dir):
        return []

    def _collect() -> list[Path]:
        results: list[Path] = []
        for entry in skills_dir.iterdir():
            if not entry.is_dir():
                continue
            candidate = entry / "SKILL.md"
            if candidate.is_file():
                results.append(candidate)
        return results

    return await asyncio.to_thread(_collect)


async def _copy_file(src: Path, dst: Path) -> None:
    async with aiofiles.open(src, "rb") as reader, aiofiles.open(dst, "wb") as writer:
        while True:
            chunk = await reader.read(1024 * 128)
            if not chunk:
                break
            await writer.write(chunk)


async def _copy_tree(src: Path, dst: Path) -> None:
    def _walk() -> list[tuple[Path, list[str], list[str]]]:
        return [(Path(root), dirs, files) for root, dirs, files in os.walk(src)]

    for root, dirs, files in await asyncio.to_thread(_walk):
        rel = root.relative_to(src)
        target_dir = dst / rel
        await aiofiles.os.makedirs(target_dir, exist_ok=True)
        for filename in files:
            await _copy_file(root / filename, target_dir / filename)
        for dirname in dirs:
            await aiofiles.os.makedirs(target_dir / dirname, exist_ok=True)


async def _remove_tree(path: Path) -> None:
    if not await aiofiles.os.path.exists(path):
        return
    await asyncio.to_thread(shutil.rmtree, path, True)


def _format_candidate_list(paths: Iterable[Path]) -> str:
    return "\n".join(f"- {p}" for p in paths)


class SkillsRegistry:
    """Index and resolve skills + commands for aloop."""

    def __init__(self) -> None:
        self.skills: dict[str, SkillInfo] = {}
        self.commands: dict[str, CommandInfo] = {}

    async def load(self, cwd: str | None = None) -> None:
        root = Path(cwd or os.getcwd())
        commands_dir = root / ".aloop" / "commands"
        skills_dir = Path.home() / ".aloop" / "skills"
        self.commands = await self._load_commands(commands_dir)
        self.skills = await self._load_skills(skills_dir)

    async def _load_skills(self, skills_dir: Path) -> dict[str, SkillInfo]:
        results: dict[str, SkillInfo] = {}
        for skill_file in await _list_skill_files(skills_dir):
            content = await _read_text(skill_file)
            frontmatter, _ = _split_frontmatter(content)
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

    async def _load_commands(self, commands_dir: Path) -> dict[str, CommandInfo]:
        results: dict[str, CommandInfo] = {}
        for command_file in await _list_command_files(commands_dir):
            content = await _read_text(command_file)
            frontmatter, body = _split_frontmatter(content)
            name = command_file.stem
            description = str(frontmatter.get("description", "")).strip()
            requires = frontmatter.get("requires-skills", [])
            requires_list: list[str] = []
            if isinstance(requires, list):
                requires_list = [str(item).strip() for item in requires if str(item).strip()]
            elif isinstance(requires, str):
                requires_list = [requires.strip()] if requires.strip() else []
            results[name] = CommandInfo(
                name=name,
                description=description,
                path=command_file,
                requires_skills=requires_list,
                template=body.strip(),
            )
        return results

    async def load_skill_body(self, skill: SkillInfo) -> str:
        content = await _read_text(skill.path / "SKILL.md")
        _, body = _split_frontmatter(content)
        return body.strip()

    async def resolve_user_input(self, user_input: str) -> ResolvedInput:
        if user_input.startswith("$"):
            name, args = _split_invocation(user_input, "$")
            skill = self.skills.get(name)
            if not skill:
                return ResolvedInput(user_input, user_input, None, None, args)
            body = await self.load_skill_body(skill)
            rendered = _render_skill_prompt(skill.name, body, args)
            return ResolvedInput(user_input, rendered, None, skill.name, args)

        if user_input.startswith("/"):
            name, args = _split_invocation(user_input, "/")
            command = self.commands.get(name)
            if not command:
                return ResolvedInput(user_input, user_input, None, None, args)

            sections: list[str] = []
            for skill_name in command.requires_skills:
                skill = self.skills.get(skill_name)
                if not skill:
                    terminal_ui.print_warning(
                        f"Missing required skill '{skill_name}' for /{command.name}"
                    )
                    continue
                body = await self.load_skill_body(skill)
                sections.append(_render_skill_prompt(skill.name, body, ""))

            template = _render_template(command.template, args)
            sections.append(template)
            rendered = "\n\n".join(s for s in sections if s)
            return ResolvedInput(user_input, rendered, command.name, None, args)

        return ResolvedInput(user_input, user_input, None, None, "")

    async def install_skill(self, source: str) -> SkillInfo | None:
        source = source.strip()
        if not source:
            terminal_ui.print_error("Install source cannot be empty")
            return None

        if _is_git_url(source):
            return await self._install_from_git(source)

        path = Path(source).expanduser().resolve()
        return await self._install_from_path(path)

    async def uninstall_skill(self, name: str) -> bool:
        name = name.strip()
        if not name:
            terminal_ui.print_error("Skill name cannot be empty")
            return False
        target_dir = Path.home() / ".aloop" / "skills" / name
        if not await aiofiles.os.path.exists(target_dir):
            terminal_ui.print_warning(f"Skill '{name}' not found in {target_dir}")
            return False
        await _remove_tree(target_dir)
        return True

    async def _install_from_path(self, path: Path) -> SkillInfo | None:
        skill_file = path / "SKILL.md"
        if not await aiofiles.os.path.exists(skill_file):
            terminal_ui.print_error(f"SKILL.md not found at {skill_file}")
            return None

        content = await _read_text(skill_file)
        frontmatter, _ = _split_frontmatter(content)
        name = str(frontmatter.get("name", "")).strip()
        description = str(frontmatter.get("description", "")).strip()
        if not name or not description:
            terminal_ui.print_error("SKILL.md missing required name/description")
            return None

        dest_root = Path.home() / ".aloop" / "skills" / name
        if await aiofiles.os.path.exists(dest_root):
            terminal_ui.print_warning(f"Skill '{name}' already exists at {dest_root}")
            return None

        await aiofiles.os.makedirs(dest_root.parent, exist_ok=True)
        await _copy_tree(path, dest_root)

        return SkillInfo(name=name, description=description, path=dest_root)

    async def _install_from_git(self, url: str) -> SkillInfo | None:
        subdir = None
        if "#" in url:
            url, _, subdir = url.partition("#")
            subdir = subdir.strip() or None

        def _mktemp() -> str:
            return tempfile.mkdtemp(prefix="aloop-skill-")

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
                    f"{_format_candidate_list(candidates)}"
                )
                return None
            return await self._install_from_path(candidates[0])
        finally:
            await _remove_tree(temp_dir)
