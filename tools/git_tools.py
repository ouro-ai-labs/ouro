"""Git operation tools for AI agents.

This module provides comprehensive git tools for version control operations,
enabling agents to interact with git repositories effectively.
"""

import asyncio
import os
from typing import Any, Dict, List, Optional

from .base import BaseTool


class GitBaseTool(BaseTool):
    """Base class for git tools with common functionality."""

    async def _run_git_command(self, args: List[str], cwd: Optional[str] = None) -> str:
        """Execute a git command and return the output.

        Args:
            args: Git command arguments (without 'git' prefix)
            cwd: Working directory (default: current directory)

        Returns:
            Command output or error message
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                *args,
                cwd=cwd or os.getcwd(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            except TimeoutError:
                process.kill()
                await process.communicate()
                return "Error: Git command timed out"

            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""

            if process.returncode != 0:
                return f"Error: {stderr_text.strip() or stdout_text.strip()}"
            return stdout_text.strip()
        except FileNotFoundError:
            return "Error: git command not found. Is git installed?"
        except Exception as e:
            return f"Error executing git command: {str(e)}"


class GitStatusTool(GitBaseTool):
    """Get the current git status of the repository."""

    @property
    def name(self) -> str:
        return "git_status"

    @property
    def description(self) -> str:
        return """Get the current git status of the repository.

Shows:
- Current branch
- Tracked/untracked files
- Modified/staged changes
- Branch divergence status

Use this to understand the current state before making changes."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "path": {
                "type": "string",
                "description": "Path to git repository (default: current directory)",
            }
        }

    async def execute(self, path: str = ".") -> str:
        """Execute git status command."""
        return await self._run_git_command(["status"], cwd=path)


class GitDiffTool(GitBaseTool):
    """Show changes between commits, commit and working tree, etc."""

    @property
    def name(self) -> str:
        return "git_diff"

    @property
    def description(self) -> str:
        return """Show file changes in the repository.

Modes:
1. Staged changes: diff between staging area and last commit
2. Unstaged changes: diff between working tree and staging area
3. Specific files: diff for specific files
4. Commits: diff between two commits or branches

Examples:
- Show all staged changes
- Show changes in specific file
- Compare branches"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "mode": {
                "type": "string",
                "description": "Diff mode: staged, unstaged, files, or commits",
                "enum": ["staged", "unstaged", "files", "commits"],
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific files to diff (for 'files' mode)",
            },
            "commit_range": {
                "type": "string",
                "description": "Commit range like 'HEAD~1..HEAD' or 'branch1..branch2' (for 'commits' mode)",
            },
            "path": {"type": "string", "description": "Path to git repository"},
        }

    async def execute(
        self,
        mode: str = "staged",
        files: Optional[List[str]] = None,
        commit_range: str = "",
        path: str = ".",
        **kwargs,
    ) -> str:
        """Execute git diff command."""
        args = ["diff"]

        if mode == "staged":
            args.append("--cached")
        elif mode == "unstaged":
            # Default diff shows unstaged changes
            pass
        elif mode == "files" and files:
            args.extend(files)
        elif mode == "commits" and commit_range:
            args.append(commit_range)

        return await self._run_git_command(args, cwd=path)


class GitAddTool(GitBaseTool):
    """Stage files for commit."""

    @property
    def name(self) -> str:
        return "git_add"

    @property
    def description(self) -> str:
        return """Stage files for commit.

Use:
- Specific files: provide file paths
- All changes: use ["."]
- All tracked files: use ["-u"]
- All (including untracked): use ["-A"]

Always check git_status first to see what you're staging."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files to stage (e.g., ['file.py'], ['.'], ['-A'])",
            },
            "path": {"type": "string", "description": "Path to git repository"},
        }

    async def execute(self, files: List[str], path: str = ".", **kwargs) -> str:
        """Execute git add command."""
        if not files:
            return "Error: No files specified"

        args = ["add"] + files
        result = await self._run_git_command(args, cwd=path)

        if "Error" not in result:
            # Show what was staged
            staged = await self._run_git_command(["diff", "--cached", "--name-only"], cwd=path)
            if staged:
                return f"Staged files:\n{staged}"
            return "Files staged successfully"

        return result


class GitCommitTool(GitBaseTool):
    """Create a commit with a message."""

    @property
    def name(self) -> str:
        return "git_commit"

    @property
    def description(self) -> str:
        return """Create a git commit.

Requirements:
- message: Commit message describing the changes
- verify: Run pre-commit hooks (default: false for safety)

Best practices:
- Use clear, descriptive messages
- Keep first line under 50 characters
- Use body for detailed explanation if needed

Example message format:
"feat: add user authentication"
"fix: resolve null pointer in parser"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "message": {"type": "string", "description": "Commit message (required)"},
            "verify": {
                "type": "boolean",
                "description": "Run pre-commit hooks (default: false)",
                "default": False,
            },
            "path": {"type": "string", "description": "Path to git repository"},
        }

    async def execute(self, message: str, verify: bool = False, path: str = ".", **kwargs) -> str:
        """Execute git commit command."""
        if not message:
            return "Error: Commit message is required"

        args = ["commit", "-m", message]
        if not verify:
            args.append("--no-verify")

        return await self._run_git_command(args, cwd=path)


class GitLogTool(GitBaseTool):
    """Show commit history."""

    @property
    def name(self) -> str:
        return "git_log"

    @property
    def description(self) -> str:
        return """Show git commit history.

Options:
- limit: Number of commits to show (default: 10)
- oneline: Compact format (default: true)
- branch: Specific branch to show history of

Returns commit hash, author, date, and message."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "limit": {"type": "integer", "description": "Number of commits to show", "default": 10},
            "oneline": {"type": "boolean", "description": "Use compact format", "default": True},
            "branch": {"type": "string", "description": "Specific branch (optional)"},
            "path": {"type": "string", "description": "Path to git repository"},
        }

    async def execute(
        self,
        limit: int = 10,
        oneline: bool = True,
        branch: Optional[str] = None,
        path: str = ".",
        **kwargs,
    ) -> str:
        """Execute git log command."""
        args = ["log"]

        if oneline:
            args.append("--oneline")

        if limit > 0:
            args.extend(["-n", str(limit)])

        if branch:
            args.append(branch)

        return await self._run_git_command(args, cwd=path)


class GitBranchTool(GitBaseTool):
    """List, create, or delete branches."""

    @property
    def name(self) -> str:
        return "git_branch"

    @property
    def description(self) -> str:
        return """Manage git branches.

Operations:
- list: Show all branches (default)
- create: Create new branch
- delete: Delete a branch
- current: Show current branch

Examples:
- List all: no parameters
- Create: operation="create", branch="feature-x"
- Delete: operation="delete", branch="old-branch" """

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "operation": {
                "type": "string",
                "description": "Operation: list, create, delete, or current",
                "enum": ["list", "create", "delete", "current"],
                "default": "list",
            },
            "branch": {
                "type": "string",
                "description": "Branch name (for create/delete operations)",
            },
            "force": {
                "type": "boolean",
                "description": "Force delete (default: false)",
                "default": False,
            },
            "path": {"type": "string", "description": "Path to git repository"},
        }

    async def execute(
        self,
        operation: str = "list",
        branch: Optional[str] = None,
        force: bool = False,
        path: str = ".",
        **kwargs,
    ) -> str:
        """Execute git branch command."""
        if operation == "list":
            return await self._run_git_command(["branch", "-v"], cwd=path)

        elif operation == "current":
            return await self._run_git_command(["branch", "--show-current"], cwd=path)

        elif operation == "create":
            if not branch:
                return "Error: Branch name required for create operation"
            return await self._run_git_command(["branch", branch], cwd=path)

        elif operation == "delete":
            if not branch:
                return "Error: Branch name required for delete operation"
            args = ["branch"]
            if force:
                args.append("-D")
            else:
                args.append("-d")
            args.append(branch)
            return await self._run_git_command(args, cwd=path)

        return "Error: Unknown operation"


class GitCheckoutTool(GitBaseTool):
    """Switch branches or restore files."""

    @property
    def name(self) -> str:
        return "git_checkout"

    @property
    def description(self) -> str:
        return """Switch branches or restore files.

Operations:
- branch: Switch to existing branch
- new_branch: Create and switch to new branch
- file: Restore file from last commit
- commit: Checkout specific commit (detached HEAD)

Examples:
- Switch: branch="main"
- Create: new_branch="feature"
- Restore: file="path/to/file.py" """

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "branch": {"type": "string", "description": "Switch to existing branch"},
            "new_branch": {"type": "string", "description": "Create and switch to new branch"},
            "file": {"type": "string", "description": "Restore specific file from HEAD"},
            "commit": {"type": "string", "description": "Checkout specific commit/tag"},
            "path": {"type": "string", "description": "Path to git repository"},
        }

    async def execute(
        self,
        branch: Optional[str] = None,
        new_branch: Optional[str] = None,
        file: Optional[str] = None,
        commit: Optional[str] = None,
        path: str = ".",
        **kwargs,
    ) -> str:
        """Execute git checkout command."""
        args = ["checkout"]

        if new_branch:
            result = await self._run_git_command(["checkout", "-b", new_branch], cwd=path)
            if "Error" not in result:
                return f"Created and switched to branch: {new_branch}"
            return result

        if branch:
            args.append(branch)
            return await self._run_git_command(args, cwd=path)

        if file:
            args.append("--")
            args.append(file)
            return await self._run_git_command(args, cwd=path)

        if commit:
            args.append(commit)
            return await self._run_git_command(args, cwd=path)

        return "Error: Specify branch, new_branch, file, or commit"


class GitPushTool(GitBaseTool):
    """Push commits to remote repository."""

    @property
    def name(self) -> str:
        return "git_push"

    @property
    def description(self) -> str:
        return """Push commits to remote repository.

Options:
- remote: Remote name (default: origin)
- branch: Branch to push (default: current branch)
- force: Force push (use with caution!)

WARNING: Force push can overwrite remote history. Use only when you know what you're doing."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "remote": {
                "type": "string",
                "description": "Remote name (default: origin)",
                "default": "origin",
            },
            "branch": {"type": "string", "description": "Branch to push (default: current branch)"},
            "force": {
                "type": "boolean",
                "description": "Force push (WARNING: rewrites history)",
                "default": False,
            },
            "set_upstream": {
                "type": "boolean",
                "description": "Set upstream tracking",
                "default": False,
            },
            "path": {"type": "string", "description": "Path to git repository"},
        }

    async def execute(
        self,
        remote: str = "origin",
        branch: Optional[str] = None,
        force: bool = False,
        set_upstream: bool = False,
        path: str = ".",
        **kwargs,
    ) -> str:
        """Execute git push command."""
        args = ["push"]

        if force:
            args.append("--force")

        if set_upstream:
            args.append("--set-upstream")

        args.append(remote)

        if branch:
            args.append(branch)
        else:
            # Get current branch
            branch = await self._run_git_command(["branch", "--show-current"], cwd=path)
            if "Error" in branch:
                return "Error: Could not determine current branch"
            args.append(branch)

        return await self._run_git_command(args, cwd=path)


class GitPullTool(GitBaseTool):
    """Pull changes from remote repository."""

    @property
    def name(self) -> str:
        return "git_pull"

    @property
    def description(self) -> str:
        return """Pull changes from remote repository.

Options:
- remote: Remote name (default: origin)
- branch: Branch to pull (default: current branch)
- rebase: Use rebase instead of merge (default: false)"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "remote": {
                "type": "string",
                "description": "Remote name (default: origin)",
                "default": "origin",
            },
            "branch": {"type": "string", "description": "Branch to pull (default: current branch)"},
            "rebase": {
                "type": "boolean",
                "description": "Use rebase instead of merge",
                "default": False,
            },
            "path": {"type": "string", "description": "Path to git repository"},
        }

    async def execute(
        self,
        remote: str = "origin",
        branch: Optional[str] = None,
        rebase: bool = False,
        path: str = ".",
        **kwargs,
    ) -> str:
        """Execute git pull command."""
        args = ["pull"]

        if rebase:
            args.append("--rebase")

        args.append(remote)

        if branch:
            args.append(branch)
        else:
            # Get current branch
            branch = await self._run_git_command(["branch", "--show-current"], cwd=path)
            if "Error" in branch:
                return "Error: Could not determine current branch"
            args.append(branch)

        return await self._run_git_command(args, cwd=path)


class GitRemoteTool(GitBaseTool):
    """Manage remote repositories."""

    @property
    def name(self) -> str:
        return "git_remote"

    @property
    def description(self) -> str:
        return """Manage remote repositories.

Operations:
- list: Show all remotes
- add: Add a new remote
- remove: Remove a remote
- get-url: Get URL of a remote
- set-url: Change URL of a remote"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "operation": {
                "type": "string",
                "description": "Operation: list, add, remove, get-url, set-url",
                "enum": ["list", "add", "remove", "get-url", "set-url"],
            },
            "name": {"type": "string", "description": "Remote name"},
            "url": {"type": "string", "description": "Remote URL (for add/set-url)"},
            "path": {"type": "string", "description": "Path to git repository"},
        }

    async def execute(
        self,
        operation: str = "list",
        name: Optional[str] = None,
        url: Optional[str] = None,
        path: str = ".",
        **kwargs,
    ) -> str:
        """Execute git remote command."""
        args = ["remote"]

        if operation == "list":
            args.append("-v")
            return await self._run_git_command(args, cwd=path)

        elif operation == "add":
            if not name or not url:
                return "Error: Both name and url required for add operation"
            args.extend(["add", name, url])
            return await self._run_git_command(args, cwd=path)

        elif operation == "remove":
            if not name:
                return "Error: Name required for remove operation"
            args.extend(["remove", name])
            return await self._run_git_command(args, cwd=path)

        elif operation == "get-url":
            if not name:
                return "Error: Name required for get-url operation"
            args.extend(["get-url", name])
            return await self._run_git_command(args, cwd=path)

        elif operation == "set-url":
            if not name or not url:
                return "Error: Both name and url required for set-url operation"
            args.extend(["set-url", name, url])
            return await self._run_git_command(args, cwd=path)

        return "Error: Unknown operation"


class GitStashTool(GitBaseTool):
    """Stash and restore changes."""

    @property
    def name(self) -> str:
        return "git_stash"

    @property
    def description(self) -> str:
        return """Stash temporary changes.

Operations:
- push: Stash current changes
- list: Show all stashes
- pop: Restore most recent stash
- drop: Delete most recent stash

Useful for temporarily saving work to switch branches."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "operation": {
                "type": "string",
                "description": "Operation: push, list, pop, drop",
                "enum": ["push", "list", "pop", "drop"],
            },
            "message": {"type": "string", "description": "Stash message (for push)"},
            "path": {"type": "string", "description": "Path to git repository"},
        }

    async def execute(
        self, operation: str = "push", message: Optional[str] = None, path: str = ".", **kwargs
    ) -> str:
        """Execute git stash command."""
        args = ["stash"]

        if operation == "push":
            args.append("push")
            if message:
                args.extend(["-m", message])
            return await self._run_git_command(args, cwd=path)

        elif operation == "list":
            args.append("list")
            return await self._run_git_command(args, cwd=path)

        elif operation == "pop":
            args.append("pop")
            return await self._run_git_command(args, cwd=path)

        elif operation == "drop":
            args.append("drop")
            return await self._run_git_command(args, cwd=path)

        return "Error: Unknown operation"


class GitCleanTool(GitBaseTool):
    """Remove untracked files from working tree."""

    @property
    def name(self) -> str:
        return "git_clean"

    @property
    def description(self) -> str:
        return """Remove untracked files from working tree.

IMPORTANT: This is a destructive operation!

Options:
- dry_run: Show what would be removed (default: true for safety)
- force: Actually remove files (must be explicitly set to true)
- directories: Also remove untracked directories

Always use dry_run first to see what will be deleted."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "dry_run": {
                "type": "boolean",
                "description": "Show what would be removed without deleting",
                "default": True,
            },
            "force": {
                "type": "boolean",
                "description": "Actually remove files (DANGEROUS)",
                "default": False,
            },
            "directories": {
                "type": "boolean",
                "description": "Remove untracked directories too",
                "default": False,
            },
            "path": {"type": "string", "description": "Path to git repository"},
        }

    async def execute(
        self,
        dry_run: bool = True,
        force: bool = False,
        directories: bool = False,
        path: str = ".",
        **kwargs,
    ) -> str:
        """Execute git clean command."""
        if not force and not dry_run:
            return "Error: force must be True to actually delete files. Use dry_run=True first."

        args = ["clean"]

        if dry_run:
            args.append("-n")  # Show what would be done
        elif force:
            args.append("-f")  # Force delete

        if directories:
            args.append("-d")  # Remove untracked directories

        result = await self._run_git_command(args, cwd=path)

        if dry_run and "Would remove" in result:
            return f"DRY RUN - Files that would be removed:\n{result}"

        return result


# All git tools for easy registration
GIT_TOOLS = [
    GitStatusTool(),
    GitDiffTool(),
    GitAddTool(),
    GitCommitTool(),
    GitLogTool(),
    GitBranchTool(),
    GitCheckoutTool(),
    GitPushTool(),
    GitPullTool(),
    GitRemoteTool(),
    GitStashTool(),
    GitCleanTool(),
]
