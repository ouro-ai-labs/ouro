"""Context injection module for providing environment information to agents."""

import os
import platform
import subprocess
from datetime import datetime
from typing import Any, Dict


def get_working_directory() -> str:
    """Get the current working directory.

    Returns:
        Absolute path of current working directory
    """
    return os.getcwd()


def get_platform_info() -> Dict[str, str]:
    """Get platform and system information.

    Returns:
        Dictionary with platform details
    """
    return {
        "system": platform.system(),  # Linux, Darwin, Windows
        "platform": os.name,  # posix, nt
        "python_version": platform.python_version(),
    }


def get_git_status() -> Dict[str, Any]:
    """Get git repository information if available.

    Returns:
        Dictionary with git information or is_repo=False
    """
    try:
        # Check if we're in a git repository
        subprocess.run(
            ["git", "rev-parse", "--git-dir"], capture_output=True, check=True, timeout=2
        )

        # Get current branch
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True, timeout=2
        ).strip()

        # Get status (short format)
        status = subprocess.check_output(["git", "status", "--short"], text=True, timeout=2).strip()

        # Get recent commits
        recent_commits = subprocess.check_output(
            ["git", "log", "-5", "--oneline"], text=True, timeout=2
        ).strip()

        # Get main/master branch name
        try:
            main_branch = (
                subprocess.check_output(
                    ["git", "symbolic-ref", "refs/remotes/origin/HEAD"], text=True, timeout=2
                )
                .strip()
                .split("/")[-1]
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            # Fallback: try to find main or master
            main_branch = "main"  # Default assumption

        return {
            "is_repo": True,
            "branch": branch,
            "main_branch": main_branch,
            "status": status if status else "Clean working directory",
            "recent_commits": recent_commits,
            "has_uncommitted_changes": bool(status),
        }

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return {"is_repo": False}


def format_context_prompt() -> str:
    """Format environment context as a prompt section.

    Returns:
        Formatted context string with XML tags
    """
    cwd = get_working_directory()
    platform_info = get_platform_info()
    git_info = get_git_status()
    today = datetime.now().strftime("%Y-%m-%d")

    # Build context string
    lines = ["<environment>"]
    lines.append(f"Working directory: {cwd}")
    lines.append(f"Platform: {platform_info['system']} ({platform_info['platform']})")
    lines.append(f"Python version: {platform_info['python_version']}")
    lines.append(f"Today's date: {today}")

    # Add git information if available
    if git_info.get("is_repo"):
        lines.append("\nGit repository: Yes")
        lines.append(f"Current branch: {git_info['branch']}")
        lines.append(f"Main branch: {git_info['main_branch']}")
        lines.append(f"Status: {git_info['status']}")

        if git_info.get("recent_commits"):
            lines.append("\nRecent commits:")
            for commit_line in git_info["recent_commits"].split("\n"):
                lines.append(f"  {commit_line}")
    else:
        lines.append("\nGit repository: No")

    lines.append("</environment>\n")

    return "\n".join(lines)


def get_context_dict() -> Dict[str, Any]:
    """Get context information as a dictionary.

    Returns:
        Dictionary with all context information
    """
    return {
        "working_directory": get_working_directory(),
        "platform": get_platform_info(),
        "git": get_git_status(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
    }
