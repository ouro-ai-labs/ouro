# Memory Management System

The memory management system automatically optimizes token usage for long-running agent tasks, reducing costs while maintaining context quality.

## Overview

### What Problem Does It Solve?

When agents execute complex tasks with many iterations:
- Context grows with each step
- Token costs accumulate quickly
- API rate limits may be exceeded
- Older messages may not be needed

The memory system addresses this by:
- Automatically compressing old messages
- Tracking token usage and costs
- Maintaining short-term context fidelity
- Providing transparent optimization

### Key Benefits

- **30-70% Token Reduction**: Automatic compression saves significant tokens
- **Cost Optimization**: Lower API costs for long conversations
- **Transparent**: Works automatically without code changes
- **Configurable**: Multiple strategies and settings
- **Multi-Provider**: Works with Anthropic, OpenAI, Gemini

## Quick Start

### 1. Enable Memory Management

In your `.aloop/config` file:

```bash
# Enable memory management
MEMORY_ENABLED=true

# Trigger compression at this threshold
MEMORY_COMPRESSION_THRESHOLD=40000
```

### 2. Run Your Agent

No code changes needed! Memory works automatically:

```bash
python main.py --mode react --task "Your complex task here"
```

### 3. View Statistics

At the end of execution:

```
--- Memory Statistics ---
Total tokens: 45,234
Compressions: 3
Net savings: 15,678 tokens (34.7%)
Total cost: $0.0234
```

## Architecture

The memory system consists of four components:

### 1. MemoryManager

**Central orchestrator** that coordinates all memory operations.

```python
from memory import MemoryManager, MemoryConfig

config = MemoryConfig(
    max_context_tokens=100000,
    compression_threshold=40000,
    enable_compression=True
)

memory = MemoryManager(config, llm)
```

**Key Methods**:
- `add_message()`: Add a message to memory
- `get_context_for_llm()`: Get optimized context
- `get_stats()`: Get usage statistics

### 2. ShortTermMemory

**Fixed-size sliding window** that keeps recent messages in full fidelity.

```python
from memory import ShortTermMemory

# Keep last 20 messages
short_term = ShortTermMemory(max_size=20)
```

**Behavior**:
- Stores most recent N messages
- Automatically drops oldest when full
- No compression - full fidelity

### 3. WorkingMemoryCompressor

**LLM-driven compression** that summarizes old messages intelligently.

```python
from memory import WorkingMemoryCompressor

compressor = WorkingMemoryCompressor(llm, config)
compressed = await compressor.compress(old_messages)
```

**Features**:
- Uses LLM to create summaries
- Preserves important messages
- Multiple compression strategies
- Estimates compression quality

### 4. TokenTracker

**Tracks token usage and costs** across all providers.

```python
from memory import TokenTracker

tracker = TokenTracker()
tokens = tracker.count_message_tokens(message, "anthropic", "claude-3-5-sonnet")
cost = tracker.calculate_cost("claude-3-5-sonnet-20241022")
```

**Capabilities**:
- Multi-provider token counting
- Cost calculation with pricing database
- Compression savings tracking
- Budget monitoring

## Configuration

### Basic Settings

```bash
# Enable/disable memory (default: true)
MEMORY_ENABLED=true

# Start compression when context exceeds this (default: 40000)
MEMORY_COMPRESSION_THRESHOLD=40000
```

### Advanced Settings

```bash
# Number of recent messages to keep uncompressed (default: 20)
MEMORY_SHORT_TERM_SIZE=20

# Compression ratio: 0.3 = compress to 30% of original (default: 0.3)
MEMORY_COMPRESSION_RATIO=0.3

# Compression strategy (default: sliding_window)
# Options: sliding_window, selective, deletion
MEMORY_COMPRESSION_STRATEGY=sliding_window

# Preserve system prompts (default: true)
MEMORY_PRESERVE_SYSTEM_PROMPTS=true

```

### Memory Presets

**Preset 1: Aggressive Compression** (maximum savings)
```bash
MEMORY_ENABLED=true
MEMORY_COMPRESSION_THRESHOLD=30000
MEMORY_COMPRESSION_RATIO=0.2
MEMORY_SHORT_TERM_SIZE=10
MEMORY_COMPRESSION_STRATEGY=sliding_window
```

**Preset 2: Balanced** (recommended)
```bash
MEMORY_ENABLED=true
MEMORY_COMPRESSION_THRESHOLD=40000
MEMORY_COMPRESSION_RATIO=0.3
MEMORY_SHORT_TERM_SIZE=20
MEMORY_COMPRESSION_STRATEGY=sliding_window
```

**Preset 3: Conservative** (preserve more context)
```bash
MEMORY_ENABLED=true
MEMORY_COMPRESSION_THRESHOLD=60000
MEMORY_COMPRESSION_RATIO=0.5
MEMORY_SHORT_TERM_SIZE=30
MEMORY_COMPRESSION_STRATEGY=selective
```

## Compression Strategies

### 1. Sliding Window (Default)

**How it works**: Summarizes ALL old messages into a compact summary.

```bash
MEMORY_COMPRESSION_STRATEGY=sliding_window
```

**Best for**:
- Long conversations where context matters
- Tasks requiring historical awareness
- General-purpose usage

**Characteristics**:
- Token savings: 60-70%
- Context quality: Good
- Compression cost: Medium
- Example: 10,000 tokens → 3,000 tokens

**Example compression**:
```
Original (10 messages):
1. User: "Search for Python tutorials"
2. Assistant: "I'll search..."
3. Tool: "Found 10 results..."
4. Assistant: "I found..."
5-10. [more back-and-forth]

Compressed:
"Previous context: User requested Python tutorial search.
Found 10 results including official docs and video courses.
Discussed beginner vs advanced options."
```

### 2. Selective

**How it works**: Preserves important messages, compresses less critical ones.

```bash
MEMORY_COMPRESSION_STRATEGY=selective
```

**Best for**:
- Tasks with critical intermediate results
- When certain messages must be preserved
- Debugging scenarios

**Characteristics**:
- Token savings: 40-50%
- Context quality: High
- Compression cost: Higher
- Example: 10,000 tokens → 5,000 tokens

**What's preserved**:
- System prompts
- Tool calls and results
- Error messages
- Messages containing "important", "critical", etc.

### 3. Deletion

**How it works**: Simply deletes old messages without summarization.

```bash
MEMORY_COMPRESSION_STRATEGY=deletion
```

**Best for**:
- Tasks where old context isn't needed
- Sequential workflows
- Maximum cost savings

**Characteristics**:
- Token savings: 100%
- Context quality: Low (old context lost)
- Compression cost: Zero
- Example: 10,000 tokens → 0 tokens

**Warning**: Only use when old messages truly aren't needed!

## Token Tracking and Costs

### How Token Counting Works

The system uses different methods per provider:

| Provider | Method | Accuracy |
|----------|--------|----------|
| **OpenAI** | tiktoken (official) | ⭐⭐⭐⭐⭐ Exact |
| **Anthropic** | Estimation (3.5 chars/token) | ⭐⭐⭐ Good |
| **Gemini** | Estimation (4 chars/token) | ⭐⭐ Rough |
| **Unknown** | Default pricing estimate | ⭐⭐ Rough |

### Cost Calculation

Pricing is automatically loaded for common models:

```python
PRICING = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},

    # Anthropic
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},

    # Gemini
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},

    # Unknown models use default
    "default": {"input": 0.55, "output": 2.19},
}
```

Prices are per **1 million tokens**.

### Viewing Statistics

```python
stats = memory.get_stats()

print(f"Current tokens: {stats['current_tokens']}")
print(f"Total cost: ${stats['total_cost']:.4f}")
print(f"Compressions: {stats['compression_count']}")
print(f"Net savings: {stats['net_savings']} tokens")
print(f"Savings %: {stats['savings_percentage']:.1f}%")
```

### Accurate Token Tracking (Advanced)

For precise costs, pass actual token counts from LLM responses:

```python
# In your agent code
response = await llm.call_async(messages, tools)

# Extract actual usage
actual_tokens = {
    "input": response.usage.input_tokens,
    "output": response.usage.output_tokens
}

# Add to memory with actual counts
await memory.add_message(
    LLMMessage(role="assistant", content=response.content),
    actual_tokens=actual_tokens
)
```

This provides exact token counts instead of estimates.

## Usage Examples

### Example 1: Enable for Long Tasks

```python
from memory import MemoryManager, MemoryConfig
from agent.agent import ReActAgent

# Create memory config
config = MemoryConfig(
    max_context_tokens=100000,
    compression_threshold=40000,
    enable_compression=True
)

# Create agent with memory
agent = ReActAgent(
    llm=llm,
    max_iterations=20,
    tools=tools,
    memory_config=config
)

# Run task - memory works automatically
result = await agent.run("Complex multi-step task...")

# View savings
stats = agent.memory.get_stats()
print(f"Saved {stats['net_savings']} tokens (${stats['net_cost']:.4f})")
```

### Example 2: Disable for Short Tasks

```python
# For simple tasks, disable memory to reduce overhead
config = MemoryConfig(enable_compression=False)

agent = ReActAgent(llm=llm, tools=tools, memory_config=config)
result = await agent.run("Simple calculation")
```

### Example 3: Custom Compression Strategy

```python
from memory import MemoryConfig, CompressionStrategy

config = MemoryConfig(
    compression_threshold=30000,  # Compress earlier
    compression_ratio=0.2,        # More aggressive
    compression_strategy=CompressionStrategy.SELECTIVE,
    preserve_tool_calls=True      # Keep tool interactions
)

agent = ReActAgent(llm=llm, tools=tools, memory_config=config)
```

## How Compression Works

### Step-by-Step Process

1. **Message Addition**: New message added via `await add_message()`
2. **Threshold Check**: If total tokens > threshold, trigger compression
3. **Message Separation**:
   - Recent N messages → Short-term memory (preserved)
   - Older messages → Candidates for compression
4. **Compression**:
   - Format old messages for LLM
   - LLM generates concise summary
   - Create CompressedMemory object
5. **Replacement**: Replace old messages with summary
6. **Statistics Update**: Track savings and costs

### Example Compression

**Before** (50,000 tokens):
```
[System] You are a helpful assistant...
[User] Search for Python tutorials
[Assistant] I'll search for Python tutorials...
[Tool] Found 10 results: 1. Official Python Tutorial...
[Assistant] I found 10 results. The top ones are...
[User] Summarize the official tutorial
[Assistant] I'll read and summarize it...
[Tool] Content: "Python is an interpreted..."
... (30 more messages)
[User] Now create a beginner guide  <-- Recent (preserved)
[Assistant] I'll create a guide...   <-- Recent (preserved)
```

**After** (20,000 tokens):
```
[System] You are a helpful assistant...
[Compressed Summary] Previous conversation: User requested Python tutorial
search. Found and analyzed official Python tutorial and video courses.
Discussed differences between beginner and advanced resources. User
preferred official docs. Created comparison of top 3 tutorials.
[User] Now create a beginner guide  <-- Recent (preserved)
[Assistant] I'll create a guide...   <-- Recent (preserved)
```

**Savings**: 30,000 tokens (60%)

### Compression Quality

The system estimates compression quality:

```python
compressed = await compressor.compress(messages)

print(f"Original: {compressed.original_tokens} tokens")
print(f"Compressed: {compressed.compressed_tokens} tokens")
print(f"Ratio: {compressed.compression_ratio:.1%}")
print(f"Message count: {compressed.original_message_count} → 1 summary")
```

## Troubleshooting

### Issue: Token stats seem inaccurate

**Cause**: Using estimation instead of actual token counts

**Solutions**:
1. Accept ±10-15% estimation error (usually acceptable)
2. For exact costs, integrate actual token counts (see "Accurate Token Tracking" above)
3. Use OpenAI with tiktoken for exact counts

### Issue: Compression not triggering

**Checks**:
```bash
# Verify enabled
MEMORY_ENABLED=true

# Check threshold
MEMORY_COMPRESSION_THRESHOLD=40000

# Ensure task is long enough
# (needs > 40,000 tokens to trigger)
```

### Issue: Context quality degraded

**Solutions**:
1. Use `selective` strategy instead of `sliding_window`
2. Increase `MEMORY_SHORT_TERM_SIZE` to preserve more recent messages
3. Increase `MEMORY_COMPRESSION_RATIO` to keep more content


### Issue: High compression cost

**Cause**: Compression itself uses LLM tokens

**Solutions**:
1. Increase threshold to compress less frequently
2. Use `deletion` strategy (no LLM calls)
3. Use cheaper model for compression (future enhancement)

### Issue: "No pricing found for model X"

**Cause**: New/unknown model not in pricing database

**Solution**: System automatically uses default pricing estimate. If you need exact pricing:

1. Add to `memory/token_tracker.py`:
```python
PRICING = {
    # ... existing ...
    "your-model-name": {"input": X.XX, "output": Y.YY},
}
```

## Performance Impact

### Token Savings by Task Type

| Task Type | Duration | Without Memory | With Memory | Savings |
|-----------|----------|----------------|-------------|---------|
| Simple calc | 3 iterations | 2,000 tokens | 2,000 tokens | 0% |
| File operations | 10 iterations | 15,000 tokens | 12,000 tokens | 20% |
| Web research | 20 iterations | 80,000 tokens | 30,000 tokens | 62% |
| Code analysis | 30 iterations | 150,000 tokens | 50,000 tokens | 67% |

### Cost Comparison

For a 50-iteration research task with Claude Sonnet:

| Configuration | Tokens | Cost | Savings |
|---------------|--------|------|---------|
| No memory | 200,000 | $0.60 | - |
| Memory (conservative) | 120,000 | $0.36 | 40% |
| Memory (balanced) | 80,000 | $0.24 | 60% |
| Memory (aggressive) | 50,000 | $0.15 | 75% |

## Best Practices

1. **Enable by Default**: Memory has minimal overhead for short tasks
2. **Use Balanced Preset**: Start with default settings
3. **Monitor First**: Run with stats to understand savings
4. **Tune Gradually**: Adjust settings based on results
5. **Preserve Critical Data**: Use `selective` for important workflows
6. **Track Costs**: Monitor `total_cost` in statistics
7. **Test Compression**: Verify quality with representative tasks

## Advanced Topics

### Custom Compression Logic

Extend the compressor for domain-specific compression:

```python
from memory import WorkingMemoryCompressor

class CustomCompressor(WorkingMemoryCompressor):
    def _should_preserve(self, message):
        # Custom preservation logic
        if "CRITICAL:" in message.content:
            return True
        return super()._should_preserve(message)
```

### Memory Inspection

Debug memory state:

```python
# Get current messages
messages = memory.get_context_for_llm()
print(f"Total messages: {len(messages)}")

# Get short-term only
short_term = memory.short_term.get_all()
print(f"Recent messages: {len(short_term)}")

# Check if compressed
if memory.compressed_memory:
    print(f"Compressed summary: {memory.compressed_memory.summary[:100]}...")
```

### Integration with Custom Agents

```python
from agent.base import BaseAgent

class MyCustomAgent(BaseAgent):
    async def run(self, task: str) -> str:
        # Add initial message
        await self.memory.add_message(LLMMessage(role="user", content=task))

        for i in range(self.max_iterations):
            # Get optimized context
            context = self.memory.get_context_for_llm()

            # Call LLM
            response = await self.llm.call_async(messages=context)

            # Add response to memory (auto-compression if needed)
            await self.memory.add_message(
                LLMMessage(role="assistant", content=response.content)
            )

            # Check compression
            if self.memory.was_compressed_last_iteration:
                savings = self.memory.last_compression_savings
                print(f"[Compressed: saved {savings} tokens]")

        # Show final stats
        stats = self.memory.get_stats()
        print(f"Total cost: ${stats['total_cost']:.4f}")

        return final_result
```

## Future Enhancements

Planned improvements:

- **Semantic Search**: Retrieve relevant old messages instead of summarizing
- **Vector Storage**: Embed messages for intelligent retrieval
- **Session Persistence**: Save/load memory across sessions
- **Multi-Model Compression**: Use cheaper model for compression
- **Adaptive Thresholds**: Automatically adjust based on task complexity
- **Compression Preview**: Show what will be compressed before doing it

## See Also

- [Configuration Guide](configuration.md) - Memory configuration options
- [Advanced Features](advanced-features.md) - Optimization techniques
- [Examples](examples.md) - Usage examples with memory
