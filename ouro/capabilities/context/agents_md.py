"""Deterministic discovery + loading of AGENTS.md project instructions.

ouro auto-loads ``AGENTS.md`` files at agent startup, walking from the current
working directory up to the filesystem root and merging every ``AGENTS.md``
found. Files closer to the CWD are appended last so they take precedence
(nearest wins), mirroring how Claude Code assembles project memory.

Scope is intentionally minimal (see ``rfc/agents-md-autoload.md``): project-tier
upward walk only. No ``@import`` directives, no size caps, no user/global tier.
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
