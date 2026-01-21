"""Tests for tool result processing."""

from memory.tool_result_processor import ToolResultProcessor


class TestToolResultProcessor:
    """Test tool result processing.

    Note: process_result() returns (processed_result, was_modified).
    - was_modified=False means result was within threshold, returned unchanged
    - was_modified=True means result was truncated with recovery suggestions
    """

    def test_small_result_passthrough(self):
        """Small results should pass through unchanged."""
        processor = ToolResultProcessor()
        result = "Small result"

        processed, was_modified = processor.process_result("read_file", result)

        assert processed == result
        assert was_modified is False

    def test_large_result_truncation(self):
        """Large results should be truncated with recovery suggestions."""
        processor = ToolResultProcessor()
        result = "x" * 10000  # Exceeds threshold

        processed, was_modified = processor.process_result("read_file", result)

        assert len(processed) < len(result)
        assert "truncated" in processed
        assert "Recovery Options" in processed
        assert was_modified is True

    def test_truncation_preserves_beginning(self):
        """Truncation should preserve the beginning of content."""
        processor = ToolResultProcessor()
        result = "START_MARKER" + ("x" * 10000) + "END_MARKER"

        processed, _ = processor.process_result("execute_shell", result)

        assert "START_MARKER" in processed

    def test_token_estimation(self):
        """Test token estimation."""
        processor = ToolResultProcessor()

        # Rough estimate: ~3.5 chars per token
        text = "x" * 3500
        tokens = processor.estimate_tokens(text)

        assert 900 < tokens < 1100  # Should be around 1000 tokens


class TestBypassTools:
    """Test bypass tools whitelist functionality."""

    def test_bypass_tool_not_truncated(self, monkeypatch):
        """Tools in bypass list should never be truncated."""
        monkeypatch.setattr("config.Config.TOOL_RESULT_BYPASS_TOOLS", ["custom_bypass_tool"])
        processor = ToolResultProcessor()
        large_result = "x" * 100000  # Very large result

        processed, was_modified = processor.process_result("custom_bypass_tool", large_result)

        assert processed == large_result
        assert was_modified is False

    def test_non_bypass_tool_truncated(self):
        """Normal tools should be truncated when exceeding threshold."""
        processor = ToolResultProcessor()
        large_result = "x" * 100000

        processed, was_modified = processor.process_result("read_file", large_result)

        assert len(processed) < len(large_result)
        assert was_modified is True


class TestRecoverySuggestions:
    """Test recovery suggestions for truncated content."""

    def test_recovery_section_included(self):
        """Large truncated content should include recovery suggestions."""
        processor = ToolResultProcessor()
        result = "x" * 10000

        processed, _ = processor.process_result(
            "read_file", result, tool_context={"filename": "large_file.txt"}
        )

        assert "Recovery Options" in processed
        assert "Commands" in processed

    def test_recovery_for_shell(self):
        """Shell output should include shell-specific recovery commands."""
        processor = ToolResultProcessor()
        result = "output\n" * 1000

        processed, _ = processor.process_result(
            "execute_shell", result, tool_context={"command": "ls -la"}
        )

        assert "head" in processed or "tail" in processed

    def test_recovery_for_code_file(self):
        """Code files should include structure in recovery suggestions."""
        processor = ToolResultProcessor()
        python_code = (
            """
import os
import sys

class MyClass:
    def __init__(self):
        pass

    def method1(self):
        pass

def my_function():
    pass
"""
            * 200
        )  # Make it large enough

        processed, _ = processor.process_result(
            "read_file", python_code, tool_context={"filename": "test.py"}
        )

        # Should include structure info for code files
        assert "Recovery Options" in processed


class TestThresholds:
    """Test tool-specific thresholds."""

    def test_below_threshold_not_truncated(self):
        """Results below threshold should not be truncated."""
        processor = ToolResultProcessor()
        # Default threshold for read_file is 3500 chars
        result = "x" * 3000

        processed, was_modified = processor.process_result("read_file", result)

        assert was_modified is False
        assert processed == result

    def test_above_threshold_truncated(self):
        """Results above threshold should be truncated."""
        processor = ToolResultProcessor()
        # Default threshold for read_file is 3500 chars
        result = "x" * 5000

        processed, was_modified = processor.process_result("read_file", result)

        assert was_modified is True
        assert len(processed) < len(result)

    def test_different_tools_have_different_thresholds(self):
        """Different tools should have different thresholds."""
        processor = ToolResultProcessor()

        # web_fetch has threshold 5000, so 4500 chars should not be truncated
        result_4500 = "x" * 4500
        processed, was_modified = processor.process_result("web_fetch", result_4500)
        assert was_modified is False

        # read_file has threshold 3500, so 4500 chars should be truncated
        processed, was_modified = processor.process_result("read_file", result_4500)
        assert was_modified is True
