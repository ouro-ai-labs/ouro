"""Tests for tool result size limiting.

Each tool now handles its own size limit checking and returns appropriate
error messages when output exceeds the maximum allowed tokens.
"""

import shlex
import sys

from tools.advanced_file_ops import GrepTool
from tools.file_ops import FileReadTool
from tools.shell import ShellTool


class TestFileReadToolSizeLimits:
    """Test FileReadTool size limit detection and pagination."""

    async def test_small_file_passthrough(self, tmp_path):
        """Small files should be read entirely."""
        tool = FileReadTool()
        test_file = tmp_path / "small.txt"
        test_file.write_text("Hello, World!")

        result = await tool.execute(str(test_file))

        assert result == "Hello, World!"

    async def test_large_file_error_without_pagination(self, tmp_path):
        """Large files should return error when no pagination is specified."""
        tool = FileReadTool()
        test_file = tmp_path / "large.txt"
        # Create a file larger than MAX_TOKENS * CHARS_PER_TOKEN = 25000 * 4 = 100KB
        large_content = "line\n" * 30000
        test_file.write_text(large_content)

        result = await tool.execute(str(test_file))

        assert "Error: File content" in result
        assert "exceeds" in result
        assert "offset" in result.lower() or "limit" in result.lower()

    async def test_large_file_with_pagination(self, tmp_path):
        """Large files can be read with pagination."""
        tool = FileReadTool()
        test_file = tmp_path / "large.txt"
        lines = [f"line {i}\n" for i in range(100)]
        test_file.write_text("".join(lines))

        # Read first 10 lines
        result = await tool.execute(str(test_file), offset=0, limit=10)

        assert "[Lines 1-10 of 100]" in result
        assert "line 0" in result
        assert "line 9" in result
        assert "line 10" not in result

    async def test_pagination_offset(self, tmp_path):
        """Pagination offset should work correctly."""
        tool = FileReadTool()
        test_file = tmp_path / "test.txt"
        lines = [f"line {i}\n" for i in range(100)]
        test_file.write_text("".join(lines))

        # Read lines 50-59
        result = await tool.execute(str(test_file), offset=50, limit=10)

        assert "[Lines 51-60 of 100]" in result
        assert "line 50" in result
        assert "line 59" in result

    async def test_large_python_file_shows_structure(self, tmp_path):
        """Large Python files should show code structure instead of error."""
        tool = FileReadTool()
        test_file = tmp_path / "large_module.py"
        # Build a large Python file with classes and functions
        lines = [
            '"""A large module."""',
            "import os",
            "from typing import List",
            "",
        ]
        for i in range(200):
            lines.append(f"def function_{i}(x: int) -> int:")
            lines.append(f'    """Docstring for function_{i}."""')
            lines.append(f"    return x + {i}")
            lines.append("")
        # Pad to exceed MAX_TOKENS * CHARS_PER_TOKEN
        lines.append("# " + "x" * 120000)
        test_file.write_text("\n".join(lines))

        result = await tool.execute(str(test_file))

        # Should show structure, not the generic error
        assert "File too large to read fully" in result
        assert "Showing code structure instead" in result
        assert "IMPORTS" in result
        assert "FUNCTIONS" in result
        assert "function_0" in result
        assert "offset" in result.lower() and "limit" in result.lower()

    async def test_large_non_code_file_shows_error(self, tmp_path):
        """Large non-code files (.txt, .json) should return the original error."""
        tool = FileReadTool()
        test_file = tmp_path / "large.json"
        test_file.write_text('{"data": "' + "x" * 150000 + '"}')

        result = await tool.execute(str(test_file))

        assert "Error: File content" in result
        assert "exceeds" in result

    async def test_small_code_file_returns_full_content(self, tmp_path):
        """Small code files should still return full content (no truncation)."""
        tool = FileReadTool()
        test_file = tmp_path / "small.py"
        content = 'def hello():\n    return "world"\n'
        test_file.write_text(content)

        result = await tool.execute(str(test_file))

        assert result == content

    async def test_file_not_found(self):
        """Non-existent files should return error."""
        tool = FileReadTool()
        result = await tool.execute("/nonexistent/path/file.txt")

        assert "Error" in result
        assert "not found" in result


class TestShellToolSizeLimits:
    """Test ShellTool output size limit detection."""

    async def test_small_output_passthrough(self):
        """Small command output should pass through."""
        tool = ShellTool()
        result = await tool.execute("echo 'Hello, World!'")

        assert "Hello, World!" in result

    async def test_large_output_error(self):
        """Large command output should return error."""
        tool = ShellTool()
        # Generate large output (more than 25000 * 4 = 100KB)
        python_cmd = shlex.quote(sys.executable)
        result = await tool.execute(f"{python_cmd} -c \"print('x' * 150000)\"")

        assert "Error: Command output" in result
        assert "exceeds" in result
        assert "head" in result.lower() or "tail" in result.lower() or "grep" in result.lower()

    async def test_command_no_output(self):
        """Commands with no output should return appropriate message."""
        tool = ShellTool()
        result = await tool.execute("true")

        assert "no output" in result.lower() or result.strip() == ""


class TestGrepToolSizeLimits:
    """Test GrepTool output size limit detection."""

    async def test_small_grep_output(self, tmp_path):
        """Small grep results should pass through."""
        tool = GrepTool()
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello():\n    pass\n")

        result = await tool.execute("def", str(tmp_path))

        assert "test.py" in result

    async def test_max_results_limit(self, tmp_path):
        """Grep should respect max results limit."""
        tool = GrepTool()
        # Create files with many matches
        for i in range(100):
            (tmp_path / f"file{i}.txt").write_text("match\nmatch\nmatch\n")

        result = await tool.execute("match", str(tmp_path), mode="with_context")

        # Results should be limited (50 by default)
        assert result.count("match") <= 60  # Some margin for variations


class TestToolConstants:
    """Test that tools inherit size limit constants from BaseTool."""

    async def test_base_tool_constants(self):
        """BaseTool should define size limit constants."""
        from tools.base import BaseTool

        assert hasattr(BaseTool, "MAX_TOKENS")
        assert hasattr(BaseTool, "CHARS_PER_TOKEN")
        assert BaseTool.MAX_TOKENS > 0
        assert BaseTool.CHARS_PER_TOKEN > 0

    async def test_tools_inherit_constants(self):
        """All tools should inherit size limit constants from BaseTool."""
        from tools.base import BaseTool

        # All tools inherit from BaseTool and should have the same constants
        assert FileReadTool.MAX_TOKENS == BaseTool.MAX_TOKENS
        assert ShellTool.MAX_TOKENS == BaseTool.MAX_TOKENS
        assert GrepTool.MAX_TOKENS == BaseTool.MAX_TOKENS
