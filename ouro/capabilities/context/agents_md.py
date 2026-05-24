"""Deterministic discovery + loading of AGENTS.md project instructions.

ouro auto-loads ``AGENTS.md`` files at agent startup, walking from the current
working directory up to the filesystem root and merging every ``AGENTS.md``
found. Files closer to the CWD are appended last so they take precedence
(nearest wins), mirroring how Claude Code assembles project memory.

Scope is intentionally minimal (see ``rfc/agents-md-autoload.md``): project-tier
upward walk only. No ``@import`` directives, no size caps, no user/global tier.

Subdirectory ``AGENTS.md`` files *below* the working directory are not part of
this eager load — they are surfaced lazily by ``NestedAgentsMdRule`` when the
agent reads a file under them (see ``load_nested_instructions`` and
``rfc/nested-agents-md.md``).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from ouro.core.log import get_logger

logger = get_logger(__name__)

AGENTS_FILENAME = "AGENTS.md"


def _discover_agents_md(start_dir: str | None = None) -> list[Path]:
    """Collect ``AGENTS.md`` files from ``start_dir`` up to the filesystem root.

    Args:
        start_dir: Directory to start the upward walk from. Defaults to CWD.

    Returns:
        Paths ordered parent-first (root → ``start_dir``), so the nearest file
        is last and wins on merge.
    """
    start = Path(start_dir or os.getcwd()).resolve()
    found: list[Path] = []
    for directory in (start, *start.parents):
        candidate = directory / AGENTS_FILENAME
        if candidate.is_file():
            found.append(candidate)
    found.reverse()  # parent-first, nearest last
    return found


def _read_and_merge(paths: list[Path]) -> str:
    """Read each path and join non-empty contents with a per-file header."""
    sections: list[str] = []
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            logger.warning("Failed to read %s, skipping", path, exc_info=True)
            continue
        if not content:
            continue
        sections.append(f"# {path}\n{content}")
    return "\n\n".join(sections)


def _format(merged: str) -> str:
    """Wrap merged AGENTS.md content in a ``<project_instructions>`` block."""
    if not merged:
        return ""
    return (
        "<project_instructions>\n"
        "The following project instructions were auto-loaded from AGENTS.md "
        "files found from the working directory up to the filesystem root "
        "(nearest last; nearest takes precedence). Treat them as project "
        "context and follow them unless a higher-priority instruction "
        "overrides.\n\n"
        f"{merged}\n"
        "</project_instructions>\n"
    )


async def load_agents_md(start_dir: str | None = None) -> str:
    """Discover, merge, and format AGENTS.md project instructions.

    Args:
        start_dir: Directory to start the upward walk from. Defaults to CWD.

    Returns:
        A formatted ``<project_instructions>`` block, or ``""`` when no
        non-empty ``AGENTS.md`` is found. File I/O runs in a worker thread to
        keep the caller's event loop responsive.
    """

    def _work() -> str:
        return _format(_read_and_merge(_discover_agents_md(start_dir)))

    return await asyncio.to_thread(_work)


# --- Nested (subdirectory) loading ------------------------------------------
#
# The eager load above covers the working directory and everything above it.
# AGENTS.md files in *subdirectories* of the CWD are surfaced on demand when a
# file under them is read, via ``NestedAgentsMdRule``. These helpers are
# synchronous because the rule runs them on the per-tool-call path.


def _nested_agents_md_paths(cwd: str, file_path: str) -> list[Path]:
    """Existing ``AGENTS.md`` along the path from ``cwd`` down to ``file_path``.

    Scans only the directories strictly between ``cwd`` (exclusive) and the
    directory containing ``file_path`` (inclusive) — the single path down to the
    file, never sibling subtrees. Returns paths ordered parent-first (nearest
    last). Returns ``[]`` when ``file_path`` sits at the ``cwd`` level or outside
    ``cwd``; those directories are already covered by the eager startup load.
    """
    cwd_abs = os.path.abspath(cwd)
    target_dir = os.path.dirname(os.path.abspath(file_path))
    try:
        within = os.path.commonpath([cwd_abs, target_dir]) == cwd_abs
    except ValueError:
        return []  # different drives / mixed roots (Windows)
    if not within or target_dir == cwd_abs:
        return []

    found: list[Path] = []
    directory = target_dir
    while directory != cwd_abs:
        candidate = Path(directory) / AGENTS_FILENAME
        if candidate.is_file():
            found.append(candidate)
        parent = os.path.dirname(directory)
        if parent == directory:
            break  # reached filesystem root without hitting cwd (defensive)
        directory = parent
    found.reverse()  # parent-first, nearest last
    return found


def _format_nested(merged: str) -> str:
    """Wrap merged subdirectory AGENTS.md in a ``<project_instructions>`` block."""
    if not merged:
        return ""
    return (
        "<project_instructions>\n"
        "Additional project instructions were auto-loaded from AGENTS.md files "
        "in subdirectories on the path to the file you just accessed (nearest "
        "last; nearest takes precedence). Follow them while working under those "
        "subdirectories unless a higher-priority instruction overrides.\n\n"
        f"{merged}\n"
        "</project_instructions>\n"
    )


def load_nested_instructions(cwd: str, file_path: str, already_injected: set[str]) -> str:
    """Read subdirectory AGENTS.md newly relevant to ``file_path`` and format them.

    Walks the directories between ``cwd`` and ``file_path``'s directory, skips
    AGENTS.md already recorded in ``already_injected`` (by string path), reads
    the rest, records them in ``already_injected``, and returns a formatted
    ``<project_instructions>`` block (or ``""`` when nothing new applies).

    ``already_injected`` is mutated in place; paths are recorded even when their
    content is empty/unreadable so they are not re-read on a later trigger.
    """
    paths = _nested_agents_md_paths(cwd, file_path)
    fresh = [p for p in paths if str(p) not in already_injected]
    if not fresh:
        return ""
    already_injected.update(str(p) for p in fresh)
    return _format_nested(_read_and_merge(fresh))
