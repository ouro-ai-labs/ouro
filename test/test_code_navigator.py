"""Tests for CodeNavigatorTool."""

import pytest

from tools.code_navigator import CodeNavigatorTool


@pytest.fixture
def sample_python_files(tmp_path):
    """Create sample Python files for testing."""
    # File 1: base.py with class and functions
    base_file = tmp_path / "base.py"
    base_file.write_text(
        '''"""Base module."""
import os
from typing import List, Dict

class BaseAgent:
    """Base class for all agents."""

    def __init__(self, name: str):
        """Initialize agent."""
        self.name = name

    def run(self, task: str) -> str:
        """Execute task."""
        return self._process(task)

    def _process(self, task: str) -> str:
        """Internal processing."""
        result = transform_task(task)
        return result

def transform_task(task: str) -> str:
    """Transform task input."""
    return task.upper()

def helper_function(x, y):
    """Helper for calculations."""
    return x + y
'''
    )

    # File 2: agent.py with subclass
    agent_file = tmp_path / "agent.py"
    agent_file.write_text(
        '''"""Agent implementation."""
from base import BaseAgent, transform_task

class ReActAgent(BaseAgent):
    """ReAct agent implementation."""

    def __init__(self, name: str, max_iter: int = 10):
        super().__init__(name)
        self.max_iter = max_iter

    def run(self, task: str) -> str:
        """Run ReAct loop."""
        processed = transform_task(task)
        return self._execute(processed)

    def _execute(self, task: str) -> str:
        """Execute with iterations."""
        return task
'''
    )

    # File 3: utils.py with utility functions
    utils_file = tmp_path / "utils.py"
    utils_file.write_text(
        '''"""Utility functions."""

def transform_task(text: str) -> str:
    """Transform text."""
    return text.lower()

def calculate(a: int, b: int) -> int:
    """Calculate sum."""
    return a + b
'''
    )

    return tmp_path


@pytest.fixture
def tool():
    """Create CodeNavigatorTool instance."""
    return CodeNavigatorTool()


class TestFindFunction:
    """Test find_function functionality."""

    def test_find_single_function(self, tool, sample_python_files):
        """Test finding a function that exists once."""
        result = tool.execute(
            target="helper_function", search_type="find_function", path=str(sample_python_files)
        )

        assert "helper_function" in result
        assert "base.py" in result
        assert "def helper_function(x, y)" in result
        assert "Helper for calculations" in result

    def test_find_multiple_functions(self, tool, sample_python_files):
        """Test finding a function that exists in multiple files."""
        result = tool.execute(
            target="transform_task", search_type="find_function", path=str(sample_python_files)
        )

        assert "Found 2 function(s)" in result
        assert "base.py" in result
        assert "utils.py" in result

    def test_function_not_found(self, tool, sample_python_files):
        """Test searching for non-existent function."""
        result = tool.execute(
            target="nonexistent_function",
            search_type="find_function",
            path=str(sample_python_files),
        )

        assert "No function named" in result
        assert "nonexistent_function" in result

    def test_function_with_type_hints(self, tool, sample_python_files):
        """Test that type hints are captured in signature."""
        result = tool.execute(
            target="run", search_type="find_function", path=str(sample_python_files)
        )

        assert "task: str" in result
        assert "-> str" in result


class TestFindClass:
    """Test find_class functionality."""

    def test_find_class(self, tool, sample_python_files):
        """Test finding a class."""
        result = tool.execute(
            target="BaseAgent", search_type="find_class", path=str(sample_python_files)
        )

        assert "BaseAgent" in result
        assert "base.py" in result
        assert "Methods" in result
        assert "__init__" in result
        assert "run" in result
        assert "_process" in result

    def test_find_subclass(self, tool, sample_python_files):
        """Test finding a subclass shows inheritance."""
        result = tool.execute(
            target="ReActAgent", search_type="find_class", path=str(sample_python_files)
        )

        assert "ReActAgent" in result
        assert "BaseAgent" in result  # Should show base class
        assert "agent.py" in result

    def test_class_not_found(self, tool, sample_python_files):
        """Test searching for non-existent class."""
        result = tool.execute(
            target="NonExistentClass", search_type="find_class", path=str(sample_python_files)
        )

        assert "No class named" in result


class TestShowStructure:
    """Test show_structure functionality."""

    def test_show_structure(self, tool, sample_python_files):
        """Test showing file structure."""
        base_file = sample_python_files / "base.py"
        result = tool.execute(target=str(base_file), search_type="show_structure")

        # Check for imports section
        assert "IMPORTS" in result
        assert "import os" in result
        assert "from typing import" in result

        # Check for classes section
        assert "CLASSES" in result
        assert "BaseAgent" in result

        # Check for functions section
        assert "FUNCTIONS" in result
        assert "transform_task" in result
        assert "helper_function" in result

    def test_show_structure_nonexistent_file(self, tool):
        """Test show_structure on non-existent file."""
        result = tool.execute(target="/nonexistent/file.py", search_type="show_structure")

        assert "Error" in result
        assert "does not exist" in result

    def test_show_structure_with_line_numbers(self, tool, sample_python_files):
        """Test that line numbers are included."""
        base_file = sample_python_files / "base.py"
        result = tool.execute(target=str(base_file), search_type="show_structure")

        assert "Line" in result


class TestFindUsages:
    """Test find_usages functionality."""

    def test_find_function_usages(self, tool, sample_python_files):
        """Test finding where a function is called."""
        result = tool.execute(
            target="transform_task", search_type="find_usages", path=str(sample_python_files)
        )

        assert "transform_task" in result
        # Should find usages in both base.py and agent.py
        assert "usage" in result.lower()

    def test_find_class_usages(self, tool, sample_python_files):
        """Test finding where a class is used."""
        result = tool.execute(
            target="BaseAgent", search_type="find_usages", path=str(sample_python_files)
        )

        # Should find import and inheritance
        assert "BaseAgent" in result

    def test_usages_not_found(self, tool, sample_python_files):
        """Test finding usages of something not used."""
        result = tool.execute(
            target="never_used_function", search_type="find_usages", path=str(sample_python_files)
        )

        assert "No usages" in result


class TestErrorHandling:
    """Test error handling."""

    def test_invalid_search_type(self, tool, sample_python_files):
        """Test invalid search type."""
        result = tool.execute(
            target="something", search_type="invalid_type", path=str(sample_python_files)
        )

        assert "Error" in result
        assert "Unknown search_type" in result

    def test_invalid_path(self, tool):
        """Test with invalid path."""
        result = tool.execute(
            target="something", search_type="find_function", path="/nonexistent/path"
        )

        assert "Error" in result
        assert "does not exist" in result


class TestPerformance:
    """Test performance characteristics."""

    def test_handles_syntax_errors_gracefully(self, tool, tmp_path):
        """Test that files with syntax errors are skipped."""
        # Create a file with syntax error
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def broken(\n  # Missing closing parenthesis")

        # Create a good file
        good_file = tmp_path / "good.py"
        good_file.write_text("def working():\n    pass")

        # Should still find the working function
        result = tool.execute(target="working", search_type="find_function", path=str(tmp_path))

        assert "working" in result
        assert "good.py" in result

    def test_large_number_of_files(self, tool, tmp_path):
        """Test handling many files."""
        # Create 20 files with functions
        for i in range(20):
            file = tmp_path / f"file_{i}.py"
            file.write_text(f"def function_{i}():\n    pass")

        # Should find all functions quickly
        result = tool.execute(target="function_10", search_type="find_function", path=str(tmp_path))

        assert "function_10" in result


class TestRealWorldScenarios:
    """Test with real-world scenarios."""

    def test_find_init_method(self, tool, sample_python_files):
        """Test finding __init__ methods."""
        result = tool.execute(
            target="__init__", search_type="find_function", path=str(sample_python_files)
        )

        assert "__init__" in result
        assert "Found 2 function(s)" in result  # BaseAgent and ReActAgent

    def test_private_methods(self, tool, sample_python_files):
        """Test finding private methods."""
        result = tool.execute(
            target="_process", search_type="find_function", path=str(sample_python_files)
        )

        assert "_process" in result
        assert "BaseAgent" in result or "base.py" in result


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
