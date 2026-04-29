#!/usr/bin/env python3

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

RFC_FILENAME_RE = re.compile(r"^[^/]+\.md$")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _check_rfc_numbering(root: Path) -> list[str]:
    errors: list[str] = []
    rfc_dir = root / "rfc"
    if not rfc_dir.exists():
        return errors

    for entry in sorted(rfc_dir.iterdir()):
        if not entry.is_file():
            continue
        if not RFC_FILENAME_RE.match(entry.name):
            errors.append(f"Invalid RFC filename: {entry.relative_to(root)} (must be *.md)")

    return errors


def _readlink_text(path: Path) -> str:
    try:
        return os.readlink(path)
    except OSError as e:
        raise RuntimeError(f"Failed to readlink {path}: {e}") from e


def _check_agents_symlinks(root: Path) -> list[str]:
    errors: list[str] = []

    dirs = [
        root,
        root / "agent",
        root / "tools",
        root / "llm",
        root / "memory",
        root / "utils" / "tui",
        root / "rfc",
        root / "docs",
        root / "test",
    ]

    for directory in dirs:
        if not directory.exists():
            continue

        claude = directory / "CLAUDE.md"
        agents = directory / "AGENTS.md"

        if not claude.exists():
            errors.append(f"Missing {claude.relative_to(root)}")
            continue

        if not agents.exists():
            errors.append(f"Missing {agents.relative_to(root)} (should symlink to CLAUDE.md)")
            continue

        if not agents.is_symlink():
            errors.append(f"{agents.relative_to(root)} must be a symlink to CLAUDE.md")
            continue

        target = _readlink_text(agents)
        if target not in {"CLAUDE.md", "./CLAUDE.md"}:
            errors.append(
                f"{agents.relative_to(root)} points to {target!r}, expected 'CLAUDE.md' (same directory)"
            )

    return errors


def main() -> int:
    root = _repo_root()
    errors: list[str] = []
    errors.extend(_check_rfc_numbering(root))
    errors.extend(_check_agents_symlinks(root))

    if errors:
        print("Repo invariants check failed:\n", file=sys.stderr)
        for line in errors:
            print(line, file=sys.stderr)
        return 1

    print("Repo invariants OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
