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
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


class InstallError(Exception):
    """Installation error."""


def ouro_home() -> Path:
    """Get ouro home directory."""
    return Path(os.environ.get("OURO_HOME", Path.home() / ".ouro"))


def skills_dir() -> Path:
    """Get skills installation directory."""
    return ouro_home() / "skills"


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


def validate_skill(path: Path) -> tuple[str, str]:
    """Validate a skill directory and return (name, description)."""
    skill_md = path / "SKILL.md"
    if not skill_md.exists():
        raise InstallError(f"SKILL.md not found at {path}")

    content = skill_md.read_text()
    if not content.startswith("---"):
        raise InstallError("SKILL.md missing YAML frontmatter")

    # Simple frontmatter parsing
    parts = content.split("---", 2)
    if len(parts) < 3:
        raise InstallError("Invalid SKILL.md frontmatter")

    frontmatter = parts[1].strip()
    name = ""
    description = ""

    for line in frontmatter.split("\n"):
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip("\"'")
        elif line.startswith("description:"):
            description = line.split(":", 1)[1].strip().strip("\"'")

    if not name:
        raise InstallError("SKILL.md missing 'name' field")
    if not description:
        raise InstallError("SKILL.md missing 'description' field")

    return name, description


def find_skills(repo_dir: Path) -> list[Path]:
    """Find all skills in a repository."""
    return [p.parent for p in repo_dir.rglob("SKILL.md")]


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
            candidates = find_skills(tmp_path)
            if not candidates:
                raise InstallError("No SKILL.md found in repository")
            if len(candidates) > 1:
                paths = "\n  ".join(str(c.relative_to(tmp_path)) for c in candidates)
                raise InstallError(f"Multiple skills found. Specify one with '#<path>':\n  {paths}")
            skill_path = candidates[0]

        name, description = validate_skill(skill_path)
        if name_override:
            name = name_override

        dest = skills_dir() / name
        if dest.exists():
            raise InstallError(f"Skill '{name}' already exists at {dest}")

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_path, dest)

        print(f"[OK] Installed '{name}' to {dest}")
        print(f"    Description: {description}")
        print("\nRestart ouro to pick up the new skill.")

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
