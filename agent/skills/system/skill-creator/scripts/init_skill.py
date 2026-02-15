#!/usr/bin/env python3
"""
Skill Initializer - Creates a new skill from template

Usage:
    init_skill.py <skill-name> --path <path> [--resources scripts,references,assets]

Examples:
    init_skill.py my-new-skill --path ~/.ouro/skills
    init_skill.py my-new-skill --path ~/.ouro/skills --resources scripts,references
    init_skill.py my-api-helper --path ~/.ouro/skills --resources scripts
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MAX_SKILL_NAME_LENGTH = 64
ALLOWED_RESOURCES = {"scripts", "references", "assets"}

SKILL_TEMPLATE = """---
name: {skill_name}
description: TODO: Describe what this skill does and when to use it. Include specific triggers and contexts.
---

# {skill_title}

TODO: Write instructions for using this skill.

## Quick Start

TODO: Add quick start guide.

## Workflow

TODO: Describe the workflow steps.
"""


def normalize_skill_name(skill_name: str) -> str:
    """Normalize a skill name to lowercase hyphen-case."""
    name = skill_name.lower().strip()
    name = re.sub(r"[^a-z0-9\-]", "-", name)
    name = re.sub(r"-+", "-", name)
    name = name.strip("-")
    return name


def title_case_skill_name(skill_name: str) -> str:
    """Convert hyphenated skill name to Title Case for display."""
    return " ".join(word.capitalize() for word in skill_name.split("-"))


def parse_resources(raw_resources: str | None) -> set[str]:
    """Parse comma-separated resource types."""
    if not raw_resources:
        return set()
    resources = set()
    for item in raw_resources.split(","):
        item = item.strip().lower()
        if item in ALLOWED_RESOURCES:
            resources.add(item)
        elif item:
            print(f"[WARN] Unknown resource type: {item}")
    return resources


def create_resource_dirs(
    skill_dir: Path,
    skill_name: str,
    skill_title: str,
    resources: set[str],
) -> None:
    """Create resource directories with placeholder files."""
    placeholders = {
        "scripts": f"""\
# {skill_title} Scripts

This directory contains executable scripts for the skill.

## Usage

Add Python, Bash, or other executable scripts here.
Scripts should be referenced from SKILL.md.
""",
        "references": f"""\
# {skill_title} References

This directory contains documentation files to be loaded into context.

## Usage

Add markdown files with schemas, API docs, style guides, etc.
Reference these files from SKILL.md when needed.
""",
        "assets": f"""\
# {skill_title} Assets

This directory contains files used in output.

## Usage

Add templates, icons, fonts, or boilerplate projects here.
Reference these from SKILL.md as needed.
""",
    }

    for resource_type in resources:
        resource_dir = skill_dir / resource_type
        resource_dir.mkdir(parents=True, exist_ok=True)
        readme = resource_dir / "README.md"
        readme.write_text(placeholders.get(resource_type, ""))
        print(f"[OK] Created {resource_type}/")


def init_skill(
    skill_name: str,
    path: str,
    resources: set[str],
) -> Path | None:
    """
    Initialize a new skill directory with template SKILL.md.

    Returns:
        Path to created skill directory, or None if error.
    """
    skill_name = normalize_skill_name(skill_name)
    if not skill_name:
        print("[ERROR] Invalid skill name")
        return None

    if len(skill_name) > MAX_SKILL_NAME_LENGTH:
        print(f"[ERROR] Skill name too long (max {MAX_SKILL_NAME_LENGTH} chars)")
        return None

    skill_dir = Path(path).expanduser().resolve() / skill_name

    if skill_dir.exists():
        print(f"[ERROR] Skill directory already exists: {skill_dir}")
        return None

    try:
        skill_dir.mkdir(parents=True, exist_ok=False)
        print(f"[OK] Created skill directory: {skill_dir}")
    except Exception as e:
        print(f"[ERROR] Error creating directory: {e}")
        return None

    skill_title = title_case_skill_name(skill_name)
    skill_content = SKILL_TEMPLATE.format(skill_name=skill_name, skill_title=skill_title)

    skill_md_path = skill_dir / "SKILL.md"
    try:
        skill_md_path.write_text(skill_content)
        print("[OK] Created SKILL.md")
    except Exception as e:
        print(f"[ERROR] Error creating SKILL.md: {e}")
        return None

    if resources:
        try:
            create_resource_dirs(skill_dir, skill_name, skill_title, resources)
        except Exception as e:
            print(f"[ERROR] Error creating resource directories: {e}")
            return None

    print(f"\n[OK] Skill '{skill_name}' initialized successfully at {skill_dir}")
    print("\nNext steps:")
    print("1. Edit SKILL.md to complete the TODO items and update the description")
    if resources:
        print("2. Add resources to scripts/, references/, and assets/ as needed")
    else:
        print("2. Create resource directories only if needed (scripts/, references/, assets/)")
    print("3. Test the skill by using it in ouro")

    return skill_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a new ouro skill from template")
    parser.add_argument("skill_name", help="Name of the skill to create")
    parser.add_argument(
        "--path",
        required=True,
        help="Path where the skill directory should be created",
    )
    parser.add_argument(
        "--resources",
        help="Comma-separated resource directories to create: scripts,references,assets",
    )

    args = parser.parse_args()

    resources = parse_resources(args.resources)
    result = init_skill(args.skill_name, args.path, resources)

    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
