# Memory Persistence

## Overview

Memory Persistence provides an embedded SQLite database for persisting conversation memory. Key features:

1. **Session Management**: Each conversation is saved as a session
2. **Batch Persistence**: Memory is saved as a batch after task completion (efficient)
3. **History Viewing**: View historical sessions and restore them
4. **Debug Support**: Dump specific session memory for debugging

## How It Works

Memory is **automatically saved** when:
- `await ReActAgent.run()` completes a task
- `await PlanExecuteAgent.run()` completes a task

You can also **manually save** by calling:
```python
manager.save_memory()  # Saves current state to database
```

This batch-save approach is more efficient than saving after every message.

## Quick Start

### 1. Using with Agent (Automatic Save)

Note: `agent.run(...)` is async; examples assume an async context.

```python
from agent import ReActAgent
from memory import MemoryConfig
from llm.anthropic import AnthropicLLM

# Initialize
llm = AnthropicLLM(api_key="your-key")
config = MemoryConfig()

# Create agent (with built-in memory persistence)
agent = ReActAgent(
    llm=llm,
    tools=[],
    memory_config=config
)

# Run task - memory is automatically saved when complete
result = await agent.run("Your task here")

print(f"Session ID: {agent.memory.session_id}")
```

### 2. Manual Save (Without Agent)

```python
from memory import MemoryConfig, MemoryManager
from llm.anthropic import AnthropicLLM
from llm.base import LLMMessage

# Initialize
llm = AnthropicLLM(api_key="your-key")
config = MemoryConfig()

# Create manager
manager = MemoryManager(
    config=config,
    llm=llm,
    db_path="data/memory.db"  # Optional, defaults to "data/memory.db"
)

# Add messages
await manager.add_message(LLMMessage(role="user", content="Hello"))
await manager.add_message(LLMMessage(role="assistant", content="Hi!"))

# Manually save to database
manager.save_memory()

print(f"Session ID: {manager.session_id}")
```

### 3. Restore Existing Session

```python
from memory import MemoryManager
from llm.anthropic import AnthropicLLM
from llm.base import LLMMessage

llm = AnthropicLLM(api_key="your-key")

# Restore from session
session_id = "your-session-id-here"
manager = MemoryManager.from_session(
    session_id=session_id,
    llm=llm,
    db_path="data/memory.db"
)

# Continue conversation
await manager.add_message(LLMMessage(role="user", content="Continue..."))

# Save after adding messages
manager.save_memory()
```

### 3. View Historical Sessions

```bash
# List all sessions
python tools/session_manager.py list

# Show specific session details
python tools/session_manager.py show <session_id>

# Show session statistics
python tools/session_manager.py stats <session_id>

# Show session messages
python tools/session_manager.py show <session_id> --messages
```

## Database Schema

### Sessions Table
Stores session basic information:
- `id`: Session UUID
- `created_at`: Creation timestamp
- `updated_at`: Update timestamp
- `metadata`: JSON metadata (description, tags, etc.)
- `config`: MemoryConfig configuration
- `current_tokens`: Current token count
- `compression_count`: Number of compressions

### Messages Table
Stores conversation messages:
- `id`: Message ID
- `session_id`: Belongs to session
- `role`: user/assistant
- `content`: JSON format content
- `tokens`: Token count
- `timestamp`: Timestamp

### System Messages Table
Stores system prompts (separate table for easier management):
- `id`: Message ID
- `session_id`: Belongs to session
- `content`: System prompt content
- `timestamp`: Timestamp

### Summaries Table
Stores compressed summaries:
- `id`: Summary ID
- `session_id`: Belongs to session
- `summary_text`: LLM generated summary
- `preserved_messages`: JSON format preserved messages
- `original_message_count`: Original message count
- `original_tokens`: Original token count
- `compressed_tokens`: Compressed token count
- `compression_ratio`: Compression ratio
- `metadata`: Compression strategy metadata
- `created_at`: Creation timestamp

## CLI Tool: session_manager.py

### List Sessions
```bash
# List all sessions (default shows 50)
python tools/session_manager.py list

# Limit number
python tools/session_manager.py list --limit 10

# Use custom database
python tools/session_manager.py --db path/to/db.db list
```

### Show Session Details
```bash
# Basic information
python tools/session_manager.py show <session_id>

# Include all messages
python tools/session_manager.py show <session_id> --messages
```

Output example:
```
📋 Session: 52f72564-e9ff-47ce-9e12-a363dea86e27
====================================================================================================

🏷️  Metadata:
  description: Demo session
  project: memory_test

📊 Statistics:
  Created: 2026-01-13 15:25:35
  Updated: 2026-01-13 15:25:35
  System Messages: 1
  Messages: 8
  Summaries: 2
  Compression Count: 2
  Current Tokens: 0

⚙️  Configuration:
  Max Context: 100,000 tokens
  Target Working Memory: 100 tokens
  Compression Threshold: 40,000 tokens
  Short-term Message Count: 5
  Compression Ratio: 0.3

📝 Summaries (2):
  ...
```

### Show Statistics
```bash
python tools/session_manager.py stats <session_id>
```

Output example:
```
📊 Session Statistics: 52f72564-...
================================================================================

⏰ Timing:
  Created: 2026-01-13 15:25:35
  Updated: 2026-01-13 15:25:35

📨 Messages:
  System Messages: 1
  Regular Messages: 8
  Total Messages: 9

🗜️  Compression:
  Compressions: 2
  Summaries: 2

🎫 Tokens:
  Current Tokens: 0
  Message Tokens: 120
  Original Tokens (pre-compression): 124
  Compressed Tokens: 26
  Token Savings: 98
  Savings Percentage: 79.0%
```

### Delete Session
```bash
# Interactive deletion (requires confirmation)
python tools/session_manager.py delete <session_id>

# Direct deletion (skip confirmation)
python tools/session_manager.py delete <session_id> --yes
```

### Update Metadata
```bash
python tools/session_manager.py meta <session_id> description "My project"
python tools/session_manager.py meta <session_id> tags "important,debug"
```

## API Documentation

### MemoryStore Class

```python
from memory.store import MemoryStore

store = MemoryStore(db_path="data/memory.db")
```

**Main Methods**:

- `create_session(metadata=None, config=None)` → str
  - Create new session
  - Returns session ID

- `save_message(session_id, message, tokens=0)`
  - Save message

- `save_summary(session_id, summary)`
  - Save compressed summary

- `load_session(session_id)` → Dict
  - Load complete session data
  - Returns dict containing messages, summaries, stats

- `list_sessions(limit=50, offset=0)` → List[Dict]
  - List sessions

- `get_session_stats(session_id)` → Dict
  - Get session statistics

- `delete_session(session_id)` → bool
  - Delete session

### MemoryManager Persistence

```python
from memory import MemoryManager, MemoryConfig

config = MemoryConfig()

# Method 1: Create new session (persistence is automatic)
manager = MemoryManager(
    config=config,
    llm=llm,
    db_path="data/memory.db"  # Optional, defaults to "data/memory.db"
)

# Method 2: Load from existing session
manager = MemoryManager.from_session(
    session_id="existing-id",
    llm=llm,
    db_path="data/memory.db"
)
```

## Use Cases

### Use Case 1: Debug Specific Conversation

```python
# 1. Record session_id when running agent
manager = MemoryManager(config, llm)
print(f"Session ID: {manager.session_id}")  # Save this ID

# 2. After encountering issues, view session details
python tools/session_manager.py show <session_id> --messages

# 3. Reload session in code for debugging
manager = MemoryManager.from_session(session_id, llm)
# Analyze memory state
print(f"Summaries: {len(manager.summaries)}")
print(f"Short-term: {manager.short_term.count()}")
```

### Use Case 2: Long-Running Conversations

```python
# Day 1: Create session (automatically persisted)
manager = MemoryManager(config, llm)
session_id = manager.session_id
save_to_config("last_session_id", session_id)

# Day 2: Continue conversation
session_id = load_from_config("last_session_id")
manager = MemoryManager.from_session(session_id, llm)
# Continue conversation...
```

### Use Case 3: A/B Testing Different Configs

```python
# Create two sessions with different configs
config_a = MemoryConfig(compression_ratio=0.3)
config_b = MemoryConfig(compression_ratio=0.5)

session_a = store.create_session(
    metadata={"experiment": "config_a"},
    config=config_a
)
session_b = store.create_session(
    metadata={"experiment": "config_b"},
    config=config_b
)

# Run same conversation
# ...

# Compare statistics
stats_a = store.get_session_stats(session_a)
stats_b = store.get_session_stats(session_b)

print(f"Config A token savings: {stats_a['token_savings']}")
print(f"Config B token savings: {stats_b['token_savings']}")
```

## Notes

1. **Database Location**: Defaults to `data/memory.db`, ensure directory exists with write permissions

2. **Session ID Management**:
   - Session ID is a UUID, should be saved properly
   - Can add description in metadata for easier identification

3. **Performance Considerations**:
   - SQLite is suitable for small to medium scale (<1000 sessions)
   - For large scale scenarios, consider periodic cleanup of old sessions

4. **Metadata Recommendations**:
   ```python
   metadata = {
       "description": "Customer support - Case #123",
       "user_id": "user_456",
       "tags": ["support", "billing"],
       "created_by": "agent_v1.2"
   }
   ```

5. **Backup**: Regularly backup the `data/memory.db` file

## Testing

Run persistence-related tests:

```bash
# Run all store tests
pytest test/memory/test_store.py -v

# Run demo
python examples/memory_persistence_demo.py
```

## FAQ

**Q: How to find a conversation's session ID?**
A: Use `python tools/session_manager.py list` to view all sessions, identify by created_at or metadata

**Q: How to clean up old sessions?**
A: Use `python tools/session_manager.py delete <session_id>` or directly delete the database file to start fresh

**Q: Can I export session as JSON?**
A: Yes, use the following in code:
```python
session_data = store.load_session(session_id)
import json
with open("session.json", "w") as f:
    json.dump(session_data, f, default=str, indent=2)
```

**Q: Does persistence affect performance?**
A: SQLite writes are very fast (<1ms), almost no impact on conversation flow

## More Examples

See `examples/memory_persistence_demo.py` for complete working examples.
