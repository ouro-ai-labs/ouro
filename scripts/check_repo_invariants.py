#!/usr/bin/env python3

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

RFC_FILENAME_RE = re.compile(r"^[^/]+\.md$")

# Top-level package roots whose subpackages must be declared in
# ``[tool.setuptools] packages``. Anything else (tests, scripts, docs)
# is excluded — only shipped code is checked.
SHIPPED_PACKAGE_ROOTS = ("ouro", "ouro_harbor")

# Capture the ``packages = [...]`` array under ``[tool.setuptools]``.
# A lightweight regex avoids a tomllib import (whose stdlib status the
# isort/ruff configs don't yet recognize) for a dev-only check.
_SETUPTOOLS_PACKAGES_RE = re.compile(
    r"\[tool\.setuptools\][^\[]*?packages\s*=\s*\[(?P<body>[^\]]*)\]",
    re.DOTALL,
)
_PACKAGE_NAME_RE = re.compile(r'"([\w.]+)"')


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

    # Updated for the three-layer architecture (commit c8d5017+):
    # core / capabilities / interfaces under the ``ouro/`` package root.
    pkg = root / "ouro"
    dirs = [
        root,
        pkg,
        pkg / "core",
        pkg / "core" / "llm",
        pkg / "capabilities",
        pkg / "capabilities" / "memory",
        pkg / "capabilities" / "tools",
        pkg / "interfaces",
        pkg / "interfaces" / "tui",
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


def _check_packages_declared(root: Path) -> list[str]:
    """Every ``__init__.py`` under shipped roots must be listed in
    ``[tool.setuptools] packages``. PyPI installs use an explicit list
    (see ouro/CLAUDE.md gotchas) — a missing subpackage ships a broken
    wheel that crashes on first import.
    """
    pyproject_text = (root / "pyproject.toml").read_text()
    match = _SETUPTOOLS_PACKAGES_RE.search(pyproject_text)
    declared: set[str] = set(_PACKAGE_NAME_RE.findall(match.group("body"))) if match else set()

    discovered: set[str] = set()
    for top in SHIPPED_PACKAGE_ROOTS:
        top_dir = root / top
        if not top_dir.exists():
            continue
        for init in top_dir.rglob("__init__.py"):
            rel = init.parent.relative_to(root)
            discovered.add(str(rel).replace(os.sep, "."))

    missing = sorted(discovered - declared)
    extra = sorted(declared - discovered)

    return [
        f"Package '{pkg}' is in source but missing from [tool.setuptools] packages "
        f"in pyproject.toml — PyPI wheel will not include it."
        for pkg in missing
    ] + [
        f"Package '{pkg}' is declared in pyproject.toml but has no "
        f"__init__.py in the source tree."
        for pkg in extra
    ]


def main() -> int:
    root = _repo_root()
    errors: list[str] = []
    errors.extend(_check_rfc_numbering(root))
    errors.extend(_check_agents_symlinks(root))
    errors.extend(_check_packages_declared(root))

    if errors:
        print("Repo invariants check failed:\n", file=sys.stderr)
        for line in errors:
            print(line, file=sys.stderr)
        return 1

    print("Repo invariants OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
