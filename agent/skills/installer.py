"""Install/uninstall helpers for skills."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Iterable

import aiofiles
import aiofiles.os

_GIT_URL_RE = re.compile(r"^(https?://|git@|ssh://)")


def is_git_url(value: str) -> bool:
    return bool(_GIT_URL_RE.match(value)) or value.endswith(".git")


async def copy_file(src: Path, dst: Path) -> None:
    async with aiofiles.open(src, "rb") as reader, aiofiles.open(dst, "wb") as writer:
        while True:
            chunk = await reader.read(1024 * 128)
            if not chunk:
                break
            await writer.write(chunk)


async def copy_tree(src: Path, dst: Path) -> None:
    def _walk() -> list[tuple[Path, list[str], list[str]]]:
        return [(Path(root), dirs, files) for root, dirs, files in os.walk(src)]

    for root, dirs, files in await asyncio.to_thread(_walk):
        rel = root.relative_to(src)
        target_dir = dst / rel
        await aiofiles.os.makedirs(target_dir, exist_ok=True)
        for filename in files:
            await copy_file(root / filename, target_dir / filename)
        for dirname in dirs:
            await aiofiles.os.makedirs(target_dir / dirname, exist_ok=True)


async def remove_tree(path: Path) -> None:
    if not await aiofiles.os.path.exists(path):
        return
    await asyncio.to_thread(shutil.rmtree, path, True)


def format_candidate_list(paths: Iterable[Path]) -> str:
    return "\n".join(f"- {p}" for p in paths)
