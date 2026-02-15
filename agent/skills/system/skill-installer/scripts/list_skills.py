#!/usr/bin/env python3
"""
List installed skills or available skills from a GitHub repository.

Usage:
    list_skills.py --installed
    list_skills.py --repo owner/repo --path skills

Examples:
    list_skills.py --installed
    list_skills.py --repo myorg/skills-repo --path skills/curated
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path


class ListError(Exception):
    """List error."""


def ouro_home() -> Path:
    """Get ouro home directory."""
    return Path(os.environ.get("OURO_HOME", Path.home() / ".ouro"))


def skills_dir() -> Path:
    """Get skills installation directory."""
    return ouro_home() / "skills"


def list_installed_skills() -> list[dict[str, str]]:
    """List installed skills with their descriptions."""
    root = skills_dir()
    if not root.exists():
        return []

    results = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue

        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            continue

        content = skill_md.read_text()
        name = entry.name
        description = ""

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].strip().split("\n"):
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip().strip("\"'")
                    elif line.startswith("description:"):
                        description = line.split(":", 1)[1].strip().strip("\"'")

        results.append(
            {
                "name": name,
                "description": description,
                "path": str(entry),
            }
        )

    return results


def github_request(url: str) -> bytes:
    """Make a GitHub API request."""
    headers = {"User-Agent": "ouro-skill-list"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def list_github_skills(repo: str, path: str, ref: str = "main") -> list[dict[str, str]]:
    """List skills from a GitHub repository."""
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
    try:
        data = json.loads(github_request(api_url).decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ListError(f"Path not found: {path} in {repo}") from e
        raise ListError(f"GitHub API error: HTTP {e.code}") from e

    if not isinstance(data, list):
        raise ListError("Unexpected response from GitHub API")

    installed = {s["name"] for s in list_installed_skills()}

    results = []
    for item in data:
        if item.get("type") != "dir":
            continue
        name = item["name"]
        results.append(
            {
                "name": name,
                "installed": name in installed,
                "url": item.get("html_url", ""),
            }
        )

    return sorted(results, key=lambda x: x["name"])


def main() -> int:
    parser = argparse.ArgumentParser(description="List ouro skills")
    parser.add_argument("--installed", action="store_true", help="List installed skills")
    parser.add_argument("--repo", help="GitHub repo (owner/repo)")
    parser.add_argument("--path", default="skills", help="Path in repo")
    parser.add_argument("--ref", default="main", help="Git ref")
    parser.add_argument("--format", choices=["text", "json"], default="text")

    args = parser.parse_args()

    try:
        if args.installed or not args.repo:
            skills = list_installed_skills()
            if args.format == "json":
                print(json.dumps(skills, indent=2))
            else:
                if not skills:
                    print("No skills installed.")
                    print(f"\nSkills directory: {skills_dir()}")
                else:
                    print("Installed skills:\n")
                    for skill in skills:
                        print(f"  {skill['name']}")
                        if skill["description"]:
                            print(f"    {skill['description'][:80]}")
                        print(f"    Path: {skill['path']}")
                        print()
        else:
            skills = list_github_skills(args.repo, args.path, args.ref)
            if args.format == "json":
                print(json.dumps(skills, indent=2))
            else:
                print(f"Skills from {args.repo}/{args.path}:\n")
                for i, skill in enumerate(skills, 1):
                    suffix = " (installed)" if skill.get("installed") else ""
                    print(f"  {i}. {skill['name']}{suffix}")
                print(
                    f"\nInstall with: python scripts/install_skill.py --url https://github.com/{args.repo}#<path>"
                )

        return 0

    except ListError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
