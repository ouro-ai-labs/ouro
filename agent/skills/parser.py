"""Parsing and rendering helpers for skills."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiofiles
import aiofiles.os
import yaml


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
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


def split_invocation(value: str, prefix: str) -> tuple[str, str]:
    stripped = value[len(prefix) :].strip()
    name, _, rest = stripped.partition(" ")
    return name.strip(), rest.strip()


def render_skill_prompt(name: str, body: str, arguments: str) -> str:
    parts = [f"SKILL: {name}", body.strip()]
    if arguments:
        parts.append(f"ARGUMENTS: {arguments}")
    return "\n\n".join(part for part in parts if part)


async def read_text(path: Path) -> str:
    async with aiofiles.open(path, encoding="utf-8") as handle:
        return await handle.read()


async def list_skill_files(skills_dir: Path) -> list[Path]:
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
