# Memory Management

## Overview

The memory system automatically compresses conversation context when it grows past a token threshold, reducing costs while preserving recent context at full fidelity. It also persists sessions as YAML files for later resumption.

Components:
- **MemoryManager** -- orchestrates compression, persistence, and context retrieval
- **ShortTermMemory** -- sliding window of recent messages (uncompressed)
- **WorkingMemoryCompressor** -- LLM-driven summarization of older messages
- **TokenTracker** -- token counting and cost tracking across providers

## Configuration

All settings go in `~/.ouro/config`:

| Setting | Default | Description |
|---------|---------|-------------|
| `MEMORY_ENABLED` | `true` | Enable memory management |
| `MEMORY_COMPRESSION_THRESHOLD` | `60000` | Token count that triggers compression |
| `MEMORY_SHORT_TERM_SIZE` | `100` | Max recent messages kept at full fidelity |
| `MEMORY_SHORT_TERM_MIN_SIZE` | `6` | Minimum messages always preserved |
| `MEMORY_COMPRESSION_RATIO` | `0.3` | Target compression ratio (0.3 = compress to 30%) |

## Compression Strategies

### sliding_window (default)

Summarizes ALL old messages into a single compact summary via LLM.

- Token savings: 60-70%
- Best for: long conversations where historical context matters

**Before** (50,000 tokens):
```
[System] You are a helpful assistant...
[User] Search for Python tutorials
[Assistant] I'll search...
[Tool] Found 10 results...
... (30 more messages)
[User] Now create a beginner guide    <-- preserved
[Assistant] I'll create a guide...    <-- preserved
```

**After** (20,000 tokens):
```
[System] You are a helpful assistant...
[Summary] User requested Python tutorial search. Found and analyzed
official tutorial and video courses. Discussed beginner vs advanced.
[User] Now create a beginner guide    <-- preserved
[Assistant] I'll create a guide...    <-- preserved
```

### selective

Preserves important messages (tool calls, errors, system prompts) and compresses the rest.

- Token savings: 40-50%
- Best for: tasks with critical intermediate results that must not be lost

### deletion

Drops old messages entirely without summarization.

- Token savings: 100%
- Compression cost: zero (no LLM call)
- Best for: sequential tasks where old context is irrelevant

## How Compression Works

1. New message added via `add_message()`
2. Token count checked against `MEMORY_COMPRESSION_THRESHOLD`
3. If over threshold:
   - Recent N messages moved to short-term memory (preserved)
   - Older messages sent to compressor
   - Compressor generates a summary via LLM
   - Old messages replaced with summary
4. Statistics updated (savings, compression count)

System prompts are always preserved regardless of strategy.

## Session Persistence

Conversations are automatically saved as YAML files when `agent.run()` completes.

### Directory Structure

```
~/.ouro/sessions/
├── .index.yaml                    # UUID-to-directory mapping (auto-managed)
├── 2025-01-31_a1b2c3d4/
│   └── session.yaml
├── 2025-01-31_e5f6g7h8/
│   └── session.yaml
└── ...
```

### Session YAML Format

```yaml
id: a1b2c3d4-5678-90ab-cdef-1234567890ab
created_at: "2025-01-31T14:30:00"
updated_at: "2025-01-31T15:45:00"

system_messages:
  - role: system
    content: |
      You are a helpful assistant.

messages:
  - role: user
    content: "Hello"
  - role: assistant
    content: null
    tool_calls:
      - id: call_abc123
        type: function
        function:
          name: calculator
          arguments: '{"expression": "2+2"}'
  - role: tool
    content: "4"
    tool_call_id: call_abc123
    name: calculator
```

### Resuming Sessions

**CLI**:
```bash
ouro --resume              # Resume most recent session
ouro --resume a1b2c3d4     # Resume by ID prefix
```

**Interactive**:
```
/resume                     # List recent sessions
/resume a1b2c3d4            # Resume by ID prefix
```

**Programmatic**:
```python
from memory import MemoryManager

# Load existing session
manager = await MemoryManager.from_session(session_id="a1b2c3d4-...", llm=llm)

# Session discovery
sessions = await MemoryManager.list_sessions(limit=20)
latest_id = await MemoryManager.find_latest_session()
full_id = await MemoryManager.find_session_by_prefix("a1b2")
```

### Session Management CLI

```bash
python tools/session_manager.py list                        # List sessions
python tools/session_manager.py show <id>                   # Session details
python tools/session_manager.py show <id> --messages        # With messages
python tools/session_manager.py stats <id>                  # Statistics
python tools/session_manager.py delete <id>                 # Delete session
```

### Implementation Notes

- Atomic writes: session files are written to `.tmp` then `os.replace()`
- Index file (`.index.yaml`) is auto-rebuilt if missing
- Session files are human-readable and can be manually edited
- Uses `aiofiles` for async I/O

## Token Tracking and Costs

Token counting method varies by provider:

| Provider | Method | Accuracy |
|----------|--------|----------|
| OpenAI | tiktoken (exact) | High |
| Anthropic | Estimation (~3.5 chars/token) | Good |
| Others | Default estimation | Approximate |

Pricing is built-in for common models (per 1M tokens). Unknown models use a default estimate.

### Viewing Statistics

In interactive mode: `/stats`

After task completion, statistics are printed automatically:
```
--- Memory Statistics ---
Total tokens: 45,234
Compressions: 3
Net savings: 15,678 tokens (34.7%)
Total cost: $0.0234
```

### Accurate Tracking

For exact costs, pass actual token counts from LLM responses:

```python
response = await llm.call_async(messages, tools)

await memory.add_message(
    LLMMessage(role="assistant", content=response.content),
    actual_tokens={
        "input": response.usage.input_tokens,
        "output": response.usage.output_tokens,
    },
)
```

## Programmatic API

```python
from memory import MemoryManager
from llm.message_types import LLMMessage

# New session
manager = MemoryManager(llm=llm)

# Add messages (compression triggers automatically)
await manager.add_message(LLMMessage(role="user", content="Hello"))
await manager.add_message(LLMMessage(role="assistant", content="Hi!"))

# Get optimized context for LLM call
context = manager.get_context_for_llm()

# Save manually (also happens automatically after agent.run())
await manager.save_memory()

# Statistics
stats = manager.get_stats()
```

## Troubleshooting

**Compression not triggering**: Check that `MEMORY_ENABLED=true` and that the conversation has exceeded `MEMORY_COMPRESSION_THRESHOLD` tokens.

**Context quality degraded after compression**: Switch to `selective` strategy, increase `MEMORY_SHORT_TERM_SIZE`, or raise `MEMORY_COMPRESSION_RATIO`.

**High compression cost**: Compression itself uses LLM tokens. Increase the threshold to compress less often, or use `deletion` strategy (zero LLM cost).

**Token estimates seem off**: Estimation accuracy varies by provider. For exact counts, pass `actual_tokens` from LLM responses (see above). OpenAI with tiktoken gives exact counts.

**Unknown model pricing**: The system uses a default estimate. To add exact pricing, edit the `PRICING` dict in `memory/token_tracker.py`.
