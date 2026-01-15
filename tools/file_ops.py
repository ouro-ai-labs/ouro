"""File operation tools for reading, writing, and searching files."""

import glob
import os
from typing import Any, Dict

from .base import BaseTool


class FileReadTool(BaseTool):
    """Read contents of a file from the filesystem."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read contents of a file from the filesystem"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "file_path": {
                "type": "string",
                "description": "Path to the file to read",
            }
        }

    def execute(self, file_path: str) -> str:
        """Read and return file contents."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
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

    def execute(self, file_path: str, content: str) -> str:
        """Write content to file."""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
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

    def execute(self, directory: str = ".", pattern: str = "*") -> str:
        """Search for files matching pattern."""
        try:
            search_path = os.path.join(directory, "**", pattern)
            files = glob.glob(search_path, recursive=True)
            if files:
                return "\n".join(files)
            else:
                return "No files found matching pattern"
        except Exception as e:
            return f"Error searching files: {str(e)}"
