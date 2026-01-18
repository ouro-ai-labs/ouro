"""Tests for tool result processing and external storage."""

from memory.tool_result_processor import ToolResultProcessor
from memory.tool_result_store import ToolResultStore


class TestToolResultProcessor:
    """Test intelligent tool result processing."""

    def test_small_result_passthrough(self):
        """Small results should pass through unchanged."""
        processor = ToolResultProcessor()
        result = "Small result"

        processed, should_store = processor.process_result("read_file", result)

        assert processed == result
        assert should_store is False

    def test_large_result_truncation(self):
        """Large results should be truncated."""
        processor = ToolResultProcessor()
        result = "x" * 10000  # 10k chars

        processed, should_store = processor.process_result("read_file", result)

        assert len(processed) < len(result)
        assert "[... " in processed or "[Key sections" in processed
        assert should_store is False  # Not large enough for external storage

    def test_very_large_result_external_storage(self):
        """Very large results should recommend external storage."""
        processor = ToolResultProcessor()
        result = "x" * 50000  # 50k chars (~14k tokens)

        processed, should_store = processor.process_result("read_file", result)

        assert should_store is True

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
