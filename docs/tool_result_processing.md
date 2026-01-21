# Tool Result Processing with Intelligent Recovery

This document describes the tool result processing system that manages large tool outputs and provides recovery suggestions for accessing truncated content.

## Overview

When tools return large outputs (e.g., reading large files, extensive search results), they can quickly consume memory tokens and trigger frequent compression. The tool result processing system addresses this with:

1. **Threshold-based Truncation**: Automatically truncate large tool results when they exceed tool-specific thresholds
2. **Recovery Suggestions**: Provide actionable suggestions for accessing truncated content using existing tools

## How It Works

When a tool result exceeds its threshold, the processor:

1. **Extracts metadata** about the content (size, line count, code structure for code files, etc.)
2. **Truncates content** to a maximum of 2,000 characters
3. **Adds recovery suggestions** with actionable commands to access the full content

### Recovery Suggestions

Instead of storing large results externally, the system provides recovery suggestions that guide the AI to access specific parts of the content using existing tools:

- **For files**: Use `grep_content` to search, or `shell` with `sed` to view specific line ranges
- **For code files**: Shows detected structure (classes, functions) with line numbers
- **For grep results**: Refine search patterns or target specific files
- **For shell output**: Use `head`/`tail`/`sed` commands to view specific sections
- **For web searches**: Refine query or fetch specific URLs
- **For web fetches**: Save to file with `save_to` parameter, then grep locally
- **For glob results**: Use more specific patterns or filter by extension

## Configuration

Configure via environment variables:

```bash
# Tools that should never be truncated (comma-separated)
TOOL_RESULT_BYPASS_TOOLS=my_special_tool,another_tool
```

### Tool-specific Thresholds

Different tools have different thresholds for triggering truncation:

| Tool | Threshold |
|------|-----------|
| `read_file` | 3,500 chars |
| `grep_content` | 3,500 chars |
| `execute_shell` | 3,500 chars |
| `web_fetch` | 5,000 chars |
| `web_search` | 4,000 chars |
| `glob_files` | 3,500 chars |
| Others | 3,500 chars |

Note: All thresholds are greater than `MAX_TRUNCATED_CHARS` (2,000) to ensure truncation always reduces size.

## Example Output

When a large file is read:

```
[First 2000 characters of content...]

[... 8000 characters truncated ...]

--- Recovery Options ---
File: large_module.py | 250 lines, 10,000 chars

Structure:
  - class DataProcessor (line 10)
  - def __init__ (line 15)
  - def process (line 30)
  - def main (line 100)

Commands:
  • grep_content(pattern="DataProcessor", path="large_module.py")
  • shell(command="sed -n '1,50p' large_module.py")  # First 50 lines
  • shell(command="sed -n '100,150p' large_module.py")  # Lines 100-150
```

## Web Fetch with Local Save

For `web_fetch`, you can save content locally for grep access:

```python
# Fetch and save to local file
web_fetch(url="https://example.com/docs", save_to="temp/docs.md")

# Then search locally
grep_content(pattern="API endpoint", path="temp/docs.md")
```

## Benefits

### Memory Efficiency

- **Reduced token usage**: Large tool results are truncated to ~2,000 chars
- **Less frequent compression**: Fewer compression cycles needed
- **Better context quality**: More room for important information

### Self-Recovery

- **No external storage needed**: Results don't need to be stored separately
- **Actionable suggestions**: AI can follow recovery suggestions to get needed content
- **Tool reuse**: Leverages existing tools (grep, shell with sed, etc.)

### Code Structure Detection

For code files, the system uses `CodeExtractor` to detect:
- Class definitions with line numbers
- Function definitions with line numbers
- Language detection based on file extension

This information is included in recovery suggestions to help navigate large code files.

## Architecture

```
Tool Execution
    |
    v
Raw Result (may be large)
    |
    v
ToolResultProcessor.process_result()
    |-- Below threshold -> Pass through unchanged
    |-- Above threshold -> Truncate + Add recovery section
    v
Processed Result
    |
    v
Add to Memory
```

### Files

- `memory/tool_result_processor.py` - Main processing logic and recovery formatting
- `memory/code_extractor.py` - Code structure extraction for recovery suggestions
- `memory/manager.py` - Integration with memory system

## See Also

- [Memory Management](memory-management.md) - Overall memory system
- [Memory Persistence](memory_persistence.md) - Session persistence
- [Configuration](configuration.md) - Full configuration options
