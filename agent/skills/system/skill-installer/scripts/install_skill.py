#!/usr/bin/env python3
"""
Install a skill from a GitHub repository.

Usage:
    install_skill.py --url <github-url>
    install_skill.py --url <github-url>#<path/to/skill>

Examples:
    install_skill.py --url https://github.com/owner/repo
    install_skill.py --url https://github.com/owner/repo#skills/my-skill
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _common import parse_skill_metadata, skills_dir


class InstallError(Exception):
    """Installation error."""


def parse_url(url: str) -> tuple[str, str | None]:
    """Parse URL and optional subpath."""
    if "#" in url:
        base_url, _, subpath = url.partition("#")
        return base_url.strip(), subpath.strip() or None
    return url.strip(), None


def clone_repo(url: str, dest: Path) -> None:
    """Clone a git repository."""
    cmd = ["git", "clone", "--depth", "1", url, str(dest)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise InstallError(f"Git clone failed: {result.stderr.strip()}")


def install_skill(url: str, name_override: str | None = None) -> Path:
    """Install a skill from a GitHub URL."""
    base_url, subpath = parse_url(url)

    with tempfile.TemporaryDirectory(prefix="ouro-skill-") as tmp:
        tmp_path = Path(tmp)
        clone_repo(base_url, tmp_path)

        if subpath:
            skill_path = tmp_path / subpath
            if not skill_path.exists():
                raise InstallError(f"Path not found: {subpath}")
        else:
            candidates = [p.parent for p in tmp_path.rglob("SKILL.md")]
            if not candidates:
                raise InstallError("No SKILL.md found in repository")
            if len(candidates) > 1:
                paths = "\n  ".join(str(c.relative_to(tmp_path)) for c in candidates)
                raise InstallError(f"Multiple skills found. Specify one with '#<path>':\n  {paths}")
            skill_path = candidates[0]

        try:
            name, description = parse_skill_metadata(skill_path)
        except ValueError as e:
            raise InstallError(str(e)) from e

        if name_override:
            name = name_override

        dest = skills_dir() / name
        if dest.exists():
            raise InstallError(f"Skill '{name}' already exists at {dest}")

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_path, dest)

        print(f"[OK] Installed '{name}' to {dest}")
        print(f"    Description: {description}")

        return dest


def main() -> int:
    parser = argparse.ArgumentParser(description="Install ouro skill from GitHub")
    parser.add_argument("--url", required=True, help="GitHub URL (use #path for subdirectory)")
    parser.add_argument("--name", help="Override skill name")

    args = parser.parse_args()

    try:
        install_skill(args.url, args.name)
        return 0
    except InstallError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
