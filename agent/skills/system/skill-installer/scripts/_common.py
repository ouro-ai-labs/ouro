"""Shared utilities for skill-installer scripts."""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def ouro_home() -> Path:
    """Get ouro home directory."""
    return Path(os.environ.get("OURO_HOME", Path.home() / ".ouro"))


def skills_dir() -> Path:
    """Get skills installation directory."""
    return ouro_home() / "skills"


def parse_skill_metadata(path: Path) -> tuple[str, str]:
    """Parse name and description from a SKILL.md file.

    Args:
        path: Path to the skill directory (containing SKILL.md).

    Returns:
        Tuple of (name, description).

    Raises:
        ValueError: If SKILL.md is missing or lacks required fields.
    """
    skill_md = path / "SKILL.md"
    if not skill_md.exists():
        raise ValueError(f"SKILL.md not found at {path}")

    content = skill_md.read_text()
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md missing YAML frontmatter")

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        raise ValueError("Invalid SKILL.md frontmatter (no closing ---)")

    yaml_text = "\n".join(lines[1:end_idx])
    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in frontmatter: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("SKILL.md frontmatter is not a mapping")

    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()

    if not name:
        raise ValueError("SKILL.md missing 'name' field")
    if not description:
        raise ValueError("SKILL.md missing 'description' field")

    return name, description
