# RFC 002: Simplified Tool Result Handling with In-Tool Size Validation

- **Status**: Draft
- **Created**: 2025-01-24
- **Author**: ouro Team

## Abstract

This RFC proposes a simplified approach to handling large tool results in LLM agent systems. Instead of using a centralized post-processor to truncate and annotate oversized outputs, we move size validation directly into each tool. When a tool detects that its output would exceed token limits, it returns a concise error message with actionable suggestions, following the pattern established by Claude Code.

## 1. Introduction

### 1.1 Background

LLM agents use tools to interact with the external world—reading files, executing commands, searching the web. These tools can produce outputs of arbitrary size, potentially overwhelming the LLM's context window or causing unnecessary token consumption.

Different systems handle this challenge in different ways:

- **Truncation-based**: Cut off large outputs and append recovery suggestions
- **Error-based**: Reject oversized outputs and guide the LLM to use alternative approaches
- **Pagination-based**: Provide parameters for reading data in chunks

### 1.2 The Current Approach

ouro currently uses a centralized `ToolResultProcessor` that:

1. Receives raw tool outputs after execution
2. Checks if output exceeds tool-specific thresholds
3. Truncates to ~2000 characters if oversized
4. Extracts metadata (code structure, file distribution, etc.)
5. Generates detailed recovery suggestions with specific commands

This approach, while comprehensive, has drawbacks:

- **Resource waste**: Large files are fully read into memory before truncation
- **Complexity**: ~540 lines of code for metadata extraction and formatting
- **Coupling**: Requires tool-specific knowledge in a central location
- **Ambiguity**: Truncated output may lead LLM to process incomplete data

### 1.3 The Claude Code Approach

Claude Code takes a different approach. When reading a large file:

```
Read(logs/xxx)
  ⎿  Error: File content (74829 tokens) exceeds maximum allowed tokens (25000).
     Please use offset and limit parameters to read specific portions of the file,
     or use the GrepTool to search for specific content.
```

Key characteristics:
- **Pre-validation**: Size checked before reading full content
- **Clear error**: Explicit token count and limit
- **Actionable guidance**: Specific alternative approaches suggested
- **No partial data**: Avoids the risk of LLM processing incomplete information

## 2. Design Philosophy

### 2.1 Core Principles

1. **Fail Fast**: Detect oversized outputs before resource-intensive operations
2. **Simple Errors**: Concise messages that guide the LLM to correct behavior
3. **Tool Autonomy**: Each tool manages its own constraints
4. **Pagination Support**: Provide mechanisms for incremental data access

### 2.2 Trade-offs

| Aspect | Centralized Processor | In-Tool Validation |
|--------|----------------------|-------------------|
| Resource efficiency | Poor (read then truncate) | Good (pre-check) |
| Code complexity | High (~540 lines) | Low (~10 lines/tool) |
| Recovery guidance | Rich (structure analysis) | Simple (generic suggestions) |
| Coupling | Low (tools unaware) | Moderate (tools know limits) |
| Partial data risk | Yes (truncated content) | No (error or full data) |

We accept moderate coupling and simpler guidance in exchange for resource efficiency, reduced complexity, and elimination of partial data risks.

## 3. Architecture

### 3.1 Before: Centralized Processing

```
┌──────────┐     ┌──────────────────┐     ┌─────────────────────┐
│   Tool   │────▶│ Raw Output       │────▶│ ToolResultProcessor │
│ Execute  │     │ (potentially     │     │ - Check thresholds  │
└──────────┘     │  very large)     │     │ - Truncate          │
                 └──────────────────┘     │ - Extract metadata  │
                                          │ - Format recovery   │
                                          └─────────────────────┘
                                                    │
                                                    ▼
                                          ┌─────────────────────┐
                                          │ Processed Result    │
                                          │ (truncated + hints) │
                                          └─────────────────────┘
```

### 3.2 After: In-Tool Validation

```
┌──────────────────────────────────────┐
│              Tool Execute             │
│  1. Pre-check size (if applicable)   │
│  2. If oversized → return error      │
│  3. If OK → execute and return       │
└──────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────┐
│  Result (error OR valid output)      │
└──────────────────────────────────────┘
```

### 3.3 Token Limits

We adopt Claude Code's token limit as a reference:

```python
MAX_TOKENS = 25000
CHARS_PER_TOKEN = 4  # Conservative estimate (actual varies by content)
```

This provides a reasonable balance between allowing substantial content and protecting the context window.

## 4. Implementation

### 4.1 File Read Tool

The `read_file` tool is the most common source of large outputs.

**Before:**
```python
def execute(self, file_path: str) -> str:
    with open(file_path, "r") as f:
        return f.read()  # No size checking
```

**After:**
```python
class FileReadTool(BaseTool):
    MAX_TOKENS = 25000
    CHARS_PER_TOKEN = 4

    def execute(self, file_path: str, offset: int = 0, limit: int = None) -> str:
        # Pre-check file size
        file_size = os.path.getsize(file_path)
        estimated_tokens = file_size // self.CHARS_PER_TOKEN

        # Reject if oversized and no pagination
        if estimated_tokens > self.MAX_TOKENS and limit is None:
            return (
                f"Error: File content (~{estimated_tokens} tokens) exceeds "
                f"maximum allowed tokens ({self.MAX_TOKENS}). Please use offset "
                f"and limit parameters to read specific portions of the file, "
                f"or use grep_content to search for specific content."
            )

        # Read with optional pagination
        with open(file_path, "r") as f:
            if limit is None:
                return f.read()
            lines = f.readlines()
            selected = lines[offset:offset + limit]
            return "".join(selected)
```

Key additions:
1. **Pre-validation**: `os.path.getsize()` before reading
2. **Pagination**: `offset` and `limit` parameters
3. **Clear error**: Token counts and alternatives

### 4.2 Shell Execution Tool

Shell commands can produce unbounded output.

```python
def execute(self, command: str) -> str:
    result = subprocess.run(command, capture_output=True, shell=True)
    output = result.stdout + result.stderr

    estimated_tokens = len(output) // 4
    if estimated_tokens > 25000:
        return (
            f"Error: Command output (~{estimated_tokens} tokens) exceeds "
            f"maximum allowed. Please pipe output through head/tail/grep, "
            f"or redirect to a file and read specific portions."
        )
    return output
```

Note: Shell output is validated post-execution since we cannot predict output size. However, this is still an improvement over truncation—the LLM receives clear feedback to adjust its approach.

### 4.3 Other Tools

| Tool | Strategy |
|------|----------|
| `grep_content` | Already has `max_results` limit; add output size check |
| `web_fetch` | Has `save_to` parameter; add content size check |
| `glob_files` | Add result count limit with clear error |
| `web_search` | Already limited by API; minimal changes needed |

### 4.4 Removed Components

The following can be removed or deprecated:

- `memory/tool_result_processor.py` (~540 lines)
- `memory/code_extractor.py` (if only used for recovery hints)
- Related integration in `agent/base.py` and `memory/manager.py`

## 5. Error Message Design

### 5.1 Structure

Error messages follow a consistent format:

```
Error: [What happened] (~{tokens} tokens) exceeds maximum allowed tokens ({limit}).
[Actionable suggestion with specific alternatives].
```

### 5.2 Examples

**File too large:**
```
Error: File content (~74829 tokens) exceeds maximum allowed tokens (25000).
Please use offset and limit parameters to read specific portions of the file,
or use grep_content to search for specific content.
```

**Shell output too large:**
```
Error: Command output (~50000 tokens) exceeds maximum allowed.
Please pipe output through head/tail/grep, or redirect to a file and read specific portions.
```

**Too many grep matches:**
```
Error: Search returned ~30000 tokens of matches.
Please use a more specific pattern or limit results with max_results parameter.
```

### 5.3 Why Simple is Better

The previous approach provided rich context:
```
--- Recovery Options ---
File: large_module.py | 2500 lines, 100,000 chars

Structure:
  - class DataProcessor (line 10)
  - def __init__ (line 15)
  - def process (line 30)
  ...

Commands:
  • grep_content(pattern="DataProcessor", path="large_module.py")
  • shell(command="sed -n '1,50p' large_module.py")
```

However:
1. **Token cost**: Detailed hints consume tokens themselves
2. **Maintenance burden**: Each tool needs custom metadata extraction
3. **Diminishing returns**: LLMs are capable of figuring out alternatives
4. **False confidence**: Rich hints might lead LLM to trust truncated data

Simple, clear errors let the LLM use its reasoning capabilities to determine the best approach.

## 6. Migration Path

### 6.1 Phase 1: Add In-Tool Validation

1. Update `read_file` with pre-validation and pagination
2. Update `execute_shell` with output size check
3. Update other tools as needed
4. Keep `ToolResultProcessor` as fallback

### 6.2 Phase 2: Remove Centralized Processor

1. Remove `ToolResultProcessor` calls from agent flow
2. Delete `memory/tool_result_processor.py`
3. Delete `memory/code_extractor.py` (if unused elsewhere)
4. Update tests

### 6.3 Backward Compatibility

For users who prefer the detailed recovery hints:
- Could keep `ToolResultProcessor` as optional feature
- Enable via configuration flag
- Default to simple in-tool validation

## 7. Comparison with Claude Code

| Aspect | Claude Code | This Proposal |
|--------|-------------|---------------|
| Pre-validation | Yes | Yes |
| Token limit | 25000 | 25000 |
| Error format | Simple, actionable | Simple, actionable |
| Pagination | offset/limit | offset/limit |
| Partial data | Never returned | Never returned |
| Rich metadata | No | No |

The proposal aligns closely with Claude Code's approach, validated in production at scale.

## 8. Testing Strategy

### 8.1 Unit Tests

```python
def test_read_file_rejects_large_file():
    tool = FileReadTool()
    # Create 200KB file (~50000 tokens)
    with open("/tmp/large.txt", "w") as f:
        f.write("x" * 200000)

    result = tool.execute("/tmp/large.txt")
    assert "Error:" in result
    assert "exceeds maximum" in result

def test_read_file_pagination_works():
    tool = FileReadTool()
    with open("/tmp/lines.txt", "w") as f:
        for i in range(1000):
            f.write(f"Line {i}\n")

    result = tool.execute("/tmp/lines.txt", offset=10, limit=5)
    assert "Line 10" in result
    assert "Line 14" in result
    assert "Line 15" not in result
```

### 8.2 Integration Tests

- Verify LLM correctly interprets error and retries with pagination
- Verify end-to-end task completion with large files
- Verify no regression in existing functionality

## 9. Conclusion

Moving size validation into tools simplifies the architecture while improving resource efficiency. The approach:

1. **Eliminates waste**: No more reading large files only to truncate them
2. **Reduces complexity**: Removes ~540 lines of centralized processing code
3. **Improves clarity**: Clear errors instead of ambiguous truncated data
4. **Enables pagination**: Tools support incremental access natively

The trade-off—simpler recovery hints—is acceptable given LLMs' capability to determine appropriate alternatives from concise error messages.

This aligns with the broader principle: let each component do one thing well. Tools execute and validate; the LLM reasons about alternatives.

## References

1. Claude Code tool implementation and error handling patterns
2. OpenAI function calling best practices
3. ouro RFC 001: Four-Phase Agent Architecture
