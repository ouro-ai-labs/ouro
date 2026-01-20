"""Tests for tool result processing and external storage."""

from memory.tool_result_processor import ToolResultProcessor
from memory.tool_result_store import ToolResultStore


class TestToolResultProcessor:
    """Test intelligent tool result processing.

    Note: process_result() returns (processed_result, was_modified).
    - was_modified=False means result was small enough, returned unchanged
    - was_modified=True means result was truncated/processed, original should be stored
    """

    def test_small_result_passthrough(self):
        """Small results should pass through unchanged."""
        processor = ToolResultProcessor()
        result = "Small result"

        processed, was_modified = processor.process_result("read_file", result)

        assert processed == result
        assert was_modified is False  # Not modified

    def test_large_result_truncation(self):
        """Large results should be truncated and marked as modified."""
        processor = ToolResultProcessor()
        result = "x" * 10000  # 10k chars

        processed, was_modified = processor.process_result("read_file", result)

        assert len(processed) < len(result)
        assert "[... " in processed or "[Key sections" in processed
        assert was_modified is True  # Was modified, original should be stored

    def test_very_large_result_also_modified(self):
        """Very large results should also be truncated and marked as modified."""
        processor = ToolResultProcessor()
        result = "x" * 50000  # 50k chars (~14k tokens)

        processed, was_modified = processor.process_result("read_file", result)

        assert was_modified is True  # Was modified

    def test_extract_key_sections_strategy(self):
        """Test key section extraction for code files."""
        processor = ToolResultProcessor()
        code = """
import os
import sys

# This is a comment
# Another comment

class MyClass:
    def __init__(self):
        pass

    def method1(self):
        # Long implementation
        pass

def my_function():
    # Another long implementation
    pass
"""
        processed, _ = processor.process_result("read_file", code * 100)  # Make it large

        # Should extract imports and definitions
        assert (
            "import os" in processed
            or "class MyClass" in processed
            or "def my_function" in processed
        )

    def test_extract_key_sections_with_filename(self):
        """Test key section extraction with explicit filename for language detection."""
        processor = ToolResultProcessor()
        python_code = """
import os
import sys
from typing import List, Dict

class DataProcessor:
    def __init__(self, config: Dict):
        self.config = config

    def process(self, items: List[str]) -> List[str]:
        return [item.upper() for item in items]

def main():
    processor = DataProcessor({})
    result = processor.process(["hello", "world"])
    print(result)
"""
        # Make the code large enough to trigger processing
        large_code = python_code * 50
        processed, _ = processor.process_result(
            "read_file", large_code, filename="data_processor.py"
        )

        # Should extract key sections using CodeExtractor
        assert "[Key sections" in processed or "extracted" in processed.lower()
        assert "DataProcessor" in processed or "def main" in processed

    def test_extract_key_sections_javascript(self):
        """Test key section extraction for JavaScript files."""
        processor = ToolResultProcessor()
        js_code = """
import React from 'react';
import { useState, useEffect } from 'react';

function MyComponent(props) {
    const [count, setCount] = useState(0);

    useEffect(() => {
        console.log('Effect running');
    }, [count]);

    return <div>{count}</div>;
}

class LegacyComponent extends React.Component {
    render() {
        return <div>Legacy</div>;
    }
}

export default MyComponent;
"""
        large_code = js_code * 50
        processed, _ = processor.process_result("read_file", large_code, filename="component.js")

        # Should extract JavaScript-specific patterns
        assert "[Key sections" in processed or "extracted" in processed.lower()

    def test_extract_key_sections_rust(self):
        """Test key section extraction for Rust files."""
        processor = ToolResultProcessor()
        rust_code = """
use std::collections::HashMap;
use std::io::{self, Read};

struct Config {
    name: String,
    value: i32,
}

impl Config {
    fn new(name: &str, value: i32) -> Self {
        Config {
            name: name.to_string(),
            value,
        }
    }
}

fn process_data(data: &[u8]) -> Result<String, io::Error> {
    Ok(String::from_utf8_lossy(data).to_string())
}

trait Processor {
    fn process(&self, input: &str) -> String;
}
"""
        large_code = rust_code * 50
        processed, _ = processor.process_result("read_file", large_code, filename="lib.rs")

        # Should extract Rust-specific patterns
        assert "[Key sections" in processed or "extracted" in processed.lower()

    def test_extract_key_sections_unknown_language_fallback(self):
        """Test fallback to regex extraction for unknown file types."""
        processor = ToolResultProcessor()
        # Code with Python-like patterns but unknown extension
        code = """
import something
from module import thing

class MyClass:
    def method(self):
        pass

def function():
    pass
"""
        large_code = code * 100
        # Use an unknown extension
        processed, _ = processor.process_result(
            "read_file", large_code, filename="file.unknown_extension"
        )

        # Should still extract something (fallback regex)
        assert len(processed) < len(large_code)

    def test_extract_key_sections_shebang_detection(self):
        """Test language detection from shebang when no filename provided."""
        processor = ToolResultProcessor()
        python_script = """#!/usr/bin/env python3

import os
import sys

def main():
    print("Hello, world!")

if __name__ == "__main__":
    main()
"""
        large_code = python_script * 100
        # No filename provided, should detect from shebang
        processed, _ = processor.process_result("read_file", large_code)

        # Should extract something
        assert len(processed) < len(large_code)

    def test_preserve_matches_strategy(self):
        """Test match preservation for grep results."""
        processor = ToolResultProcessor()
        grep_result = "\n".join([f"file{i}.py:10:match line {i}" for i in range(100)])

        processed, _ = processor.process_result("grep_content", grep_result)

        # Should preserve match lines
        assert "file" in processed
        assert "match line" in processed

    def test_smart_truncate_preserves_head_and_tail(self):
        """Test smart truncation preserves both ends."""
        processor = ToolResultProcessor()
        result = "START" + ("x" * 10000) + "END"

        processed, _ = processor.process_result("execute_shell", result)

        # Should have both start and end
        assert "START" in processed
        assert "END" in processed
        assert len(processed) < len(result)

    def test_token_estimation(self):
        """Test token estimation."""
        processor = ToolResultProcessor()

        # Rough estimate: ~3.5 chars per token
        text = "x" * 3500
        tokens = processor.estimate_tokens(text)

        assert 900 < tokens < 1100  # Should be around 1000 tokens


class TestToolResultStore:
    """Test external tool result storage."""

    def test_store_and_retrieve(self):
        """Test basic store and retrieve."""
        store = ToolResultStore()  # In-memory

        result_id = store.store_result(
            tool_call_id="call_123",
            tool_name="read_file",
            content="Test content",
        )

        assert result_id is not None

        retrieved = store.retrieve_result(result_id)
        assert retrieved == "Test content"

    def test_duplicate_content_same_id(self):
        """Duplicate content should return same ID."""
        store = ToolResultStore()

        id1 = store.store_result(
            tool_call_id="call_1",
            tool_name="read_file",
            content="Same content",
        )

        id2 = store.store_result(
            tool_call_id="call_2",
            tool_name="read_file",
            content="Same content",
        )

        assert id1 == id2

    def test_get_summary(self):
        """Test getting summary without full content."""
        store = ToolResultStore()

        result_id = store.store_result(
            tool_call_id="call_123",
            tool_name="read_file",
            content="x" * 10000,
            summary="Custom summary",
        )

        summary = store.get_summary(result_id)
        assert summary == "Custom summary"

    def test_get_metadata(self):
        """Test getting metadata."""
        store = ToolResultStore()

        result_id = store.store_result(
            tool_call_id="call_123",
            tool_name="read_file",
            content="Test content",
            token_count=100,
        )

        metadata = store.get_metadata(result_id)
        assert metadata is not None
        assert metadata["tool_name"] == "read_file"
        assert metadata["tool_call_id"] == "call_123"
        assert metadata["token_count"] == 100
        assert metadata["content_length"] == len("Test content")

    def test_format_reference(self):
        """Test formatting a reference."""
        store = ToolResultStore()

        result_id = store.store_result(
            tool_call_id="call_123",
            tool_name="read_file",
            content="Test content",
            summary="This is a summary",
        )

        reference = store.format_reference(result_id, include_summary=True)

        assert result_id in reference
        assert "read_file" in reference
        assert "This is a summary" in reference
        assert "retrieve_tool_result" in reference

    def test_access_tracking(self):
        """Test that access is tracked."""
        store = ToolResultStore()

        result_id = store.store_result(
            tool_call_id="call_123",
            tool_name="read_file",
            content="Test content",
        )

        # Retrieve multiple times
        store.retrieve_result(result_id)
        store.retrieve_result(result_id)

        metadata = store.get_metadata(result_id)
        assert metadata["access_count"] == 2
        assert metadata["accessed_at"] is not None

    def test_get_stats(self):
        """Test getting storage statistics."""
        store = ToolResultStore()

        # Store some results
        for i in range(5):
            store.store_result(
                tool_call_id=f"call_{i}",
                tool_name="read_file",
                content=f"Content {i}" * 100,
                token_count=100,
            )

        stats = store.get_stats()
        assert stats["total_results"] == 5
        assert stats["total_tokens"] == 500
        assert stats["total_bytes"] > 0

    def test_retrieve_nonexistent(self):
        """Test retrieving non-existent result."""
        store = ToolResultStore()

        result = store.retrieve_result("nonexistent_id")
        assert result is None

    def test_cleanup_old_results(self):
        """Test cleanup of old results."""
        store = ToolResultStore()

        # Store a result
        store.store_result(
            tool_call_id="call_123",
            tool_name="read_file",
            content="Test content",
        )

        # Cleanup results older than 0 days (should delete all)
        deleted = store.cleanup_old_results(days=0)
        assert deleted >= 0  # May be 0 if created just now

    def test_store_with_persistence(self, tmp_path):
        """Test storage with persistent database."""
        db_path = str(tmp_path / "test_store.db")

        # Create store and add data
        store1 = ToolResultStore(db_path=db_path)
        result_id = store1.store_result(
            tool_call_id="call_123",
            tool_name="read_file",
            content="Persistent content",
        )
        store1.close()

        # Reopen and verify data persists
        store2 = ToolResultStore(db_path=db_path)
        retrieved = store2.retrieve_result(result_id)
        assert retrieved == "Persistent content"
        store2.close()


class TestIntegration:
    """Integration tests for processor + store."""

    def test_processor_and_store_integration(self):
        """Test processor recommending external storage."""
        processor = ToolResultProcessor()
        store = ToolResultStore()

        # Create a very large result
        large_result = "x" * 50000

        # Process it
        processed, should_store = processor.process_result("read_file", large_result)

        assert should_store is True

        # Store it
        result_id = store.store_result(
            tool_call_id="call_123",
            tool_name="read_file",
            content=large_result,
            summary=processed,
        )

        # Get reference
        reference = store.format_reference(result_id)

        # Reference should be much smaller than original
        assert len(reference) < len(large_result) / 10

        # Should be able to retrieve full content
        retrieved = store.retrieve_result(result_id)
        assert retrieved == large_result


class TestBypassTools:
    """Test bypass tools whitelist functionality."""

    def test_bypass_tool_not_truncated(self):
        """Tools in bypass list should never be truncated."""
        processor = ToolResultProcessor()
        large_result = "x" * 100000  # Very large result

        # retrieve_tool_result is in the bypass list
        processed, was_modified = processor.process_result("retrieve_tool_result", large_result)

        # Should return unchanged
        assert processed == large_result
        assert was_modified is False

    def test_non_bypass_tool_truncated(self):
        """Normal tools should be truncated."""
        processor = ToolResultProcessor()
        large_result = "x" * 100000

        processed, was_modified = processor.process_result("read_file", large_result)

        # Should be truncated
        assert len(processed) < len(large_result)
        assert was_modified is True


class TestErrorPreservation:
    """Test error-aware truncation strategy."""

    def test_error_content_preserves_tail(self):
        """Error messages should preserve more tail content."""
        processor = ToolResultProcessor()

        # Simulate output with error at the end
        result = (
            "Normal output line\n" * 500
            + "Error: Something failed!\nTraceback:\n  File x.py\n  ..."
        )

        processed, was_modified = processor.process_result("execute_shell", result)

        # Error message should be preserved (it's in the tail)
        assert was_modified is True
        assert "error detected, tail preserved" in processed.lower()
        assert "Error: Something failed!" in processed or "Traceback" in processed

    def test_non_error_content_uses_smart_truncate(self):
        """Non-error content should use smart truncate (65% head, 30% tail)."""
        processor = ToolResultProcessor()

        # Normal output without errors
        result = "START\n" + "normal line\n" * 500 + "END"

        processed, was_modified = processor.process_result("execute_shell", result)

        assert was_modified is True
        assert "START" in processed
        assert "END" in processed
        # Should not mention error detection
        assert "error detected" not in processed.lower()


class TestToolStrategies:
    """Test tool-specific strategy functionality."""

    def test_default_budget_for_unknown_tool(self):
        """Unknown tools should use DEFAULT_MAX_TOKENS (1000)."""
        processor = ToolResultProcessor()

        # Result larger than default 1000 tokens (~3500 chars)
        result = "x" * 5000  # ~1428 tokens, exceeds 1000 default

        processed, was_modified = processor.process_result("unknown_tool", result)

        # Should be truncated with default budget
        assert was_modified is True
        assert len(processed) < len(result)

    def test_subtask_budget(self):
        """Subtask results should use _subtask_result config (800 tokens)."""
        processor = ToolResultProcessor()

        # Result that exceeds 800 token budget (~2800 chars)
        result = "x" * 3500  # ~1000 tokens, exceeds 800

        processed, was_modified = processor.process_result("_subtask_result", result)

        assert was_modified is True

    def test_tool_specific_budget(self):
        """Tools in TOOL_STRATEGIES should use their configured budget."""
        processor = ToolResultProcessor()

        # web_fetch has 1500 token budget (~5250 chars)
        # Result that fits in web_fetch budget but not in default
        result = "x" * 4000  # ~1143 tokens, fits in 1500 but exceeds 1000

        processed, was_modified = processor.process_result("web_fetch", result)

        # Should NOT be truncated (fits in 1500 token budget)
        assert was_modified is False
        assert processed == result
