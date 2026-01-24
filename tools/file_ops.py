"""File operation tools for reading, writing, and searching files."""

import asyncio
import glob
import os
from typing import Any, Dict

import aiofiles
import aiofiles.os

from .base import BaseTool


class FileReadTool(BaseTool):
    """Read contents of a file from the filesystem."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read contents of a file. For large files, use offset and limit "
            "parameters to read specific portions."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "file_path": {
                "type": "string",
                "description": "Path to the file to read",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start from (0-indexed). Default: 0",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read. If not set, reads entire file.",
            },
        }

    async def execute(self, file_path: str, offset: int = 0, limit: int = None) -> str:
        """Read file with optional pagination."""
        try:
            # Pre-check file size
            file_size = await aiofiles.os.path.getsize(file_path)
            estimated_tokens = file_size // self.CHARS_PER_TOKEN

            # If file too large and no pagination, return error
            if estimated_tokens > self.MAX_TOKENS and limit is None:
                return (
                    f"Error: File content (~{estimated_tokens} tokens) exceeds "
                    f"maximum allowed tokens ({self.MAX_TOKENS}). Please use offset "
                    f"and limit parameters to read specific portions of the file, "
                    f"or use grep_content to search for specific content."
                )

            async with aiofiles.open(file_path, encoding="utf-8") as f:
                if limit is None:
                    return await f.read()
                # Pagination mode
                lines = await f.readlines()
                total_lines = len(lines)
                selected = lines[offset : offset + limit]
                result = "".join(selected)
                # Add context about total lines
                if offset > 0 or offset + limit < total_lines:
                    result = f"[Lines {offset+1}-{min(offset+limit, total_lines)} of {total_lines}]\n{result}"
                return result

        except FileNotFoundError:
            return f"Error: File '{file_path}' not found"
        except Exception as e:
            return f"Error reading file: {str(e)}"


class FileWriteTool(BaseTool):
    """Write content to a file (creates or overwrites)."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file (creates or overwrites)"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "file_path": {
                "type": "string",
                "description": "Path where to write the file",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file",
            },
        }

    async def execute(self, file_path: str, content: str) -> str:
        """Write content to file."""
        try:
            # Create directory if it doesn't exist
            await aiofiles.os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(content)
            return f"Successfully wrote to {file_path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class FileSearchTool(BaseTool):
    """Search for files matching a pattern in a directory."""

    @property
    def name(self) -> str:
        return "search_files"

    @property
    def description(self) -> str:
        return "Search for files matching a pattern in a directory"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "directory": {
                "type": "string",
                "description": "Directory to search in (default: current directory)",
            },
            "pattern": {
                "type": "string",
                "description": "File name pattern (e.g., '*.py', 'test_*')",
            },
        }

    async def execute(self, directory: str = ".", pattern: str = "*") -> str:
        """Search for files matching pattern."""
        try:
            search_path = os.path.join(directory, "**", pattern)
            files = await asyncio.to_thread(lambda: glob.glob(search_path, recursive=True))
            if files:
                return "\n".join(files)
            else:
                return "No files found matching pattern"
        except Exception as e:
            return f"Error searching files: {str(e)}"
