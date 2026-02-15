"""Context injection module for providing environment information to agents."""

import asyncio
import os
import platform
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


async def _run_git_command(args: list[str], timeout: float = 2.0) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise
    returncode = process.returncode if process.returncode is not None else 0
    return (
        returncode,
        stdout.decode(errors="ignore").strip(),
        stderr.decode(errors="ignore").strip(),
    )


async def get_git_status() -> Dict[str, Any]:
    """Get git repository information if available.

    Returns:
        Dictionary with git information or is_repo=False
    """
    try:
        returncode, _, _ = await _run_git_command(["git", "rev-parse", "--git-dir"], timeout=2)
        if returncode != 0:
            return {"is_repo": False}

        _, branch, _ = await _run_git_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], 2)
        _, status, _ = await _run_git_command(["git", "status", "--short"], 2)
        _, recent_commits, _ = await _run_git_command(["git", "log", "-5", "--oneline"], 2)

        try:
            _, remote_head, _ = await _run_git_command(
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"], 2
            )
            main_branch = remote_head.split("/")[-1] if remote_head else "main"
        except asyncio.TimeoutError:
            main_branch = "main"

        return {
            "is_repo": True,
            "branch": branch,
            "main_branch": main_branch,
            "status": status if status else "Clean working directory",
            "recent_commits": recent_commits,
            "has_uncommitted_changes": bool(status),
        }

    except (asyncio.TimeoutError, FileNotFoundError):
        return {"is_repo": False}


async def format_context_prompt() -> str:
    """Format environment context as a prompt section.

    Returns:
        Formatted context string with XML tags

    Note:
        Git information is intentionally excluded to save tokens.
        Agents can use git_status, git_log, and other git tools
        to get up-to-date repository information when needed.
    """
    cwd = get_working_directory()
    platform_info = get_platform_info()
    today = datetime.now().strftime("%Y-%m-%d")

    lines = [
        "<environment>",
        f"Working directory: {cwd}",
        f"Platform: {platform_info['system']}",
        f"Today's date: {today}",
        "</environment>\n",
    ]

    return "\n".join(lines)


async def get_context_dict() -> Dict[str, Any]:
    """Get context information as a dictionary.

    Returns:
        Dictionary with all context information
    """
    return {
        "working_directory": get_working_directory(),
        "platform": get_platform_info(),
        "git": await get_git_status(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
    }
