# Advanced Features

This guide covers advanced features and optimization techniques for the Agentic Loop system.

Note: `agent.run(...)` is async; snippets that use `await` assume an async context (e.g., wrap with `asyncio.run(main())`).

## Automatic Retry with Exponential Backoff

All LLM providers support automatic retry with exponential backoff when encountering rate limit errors (429). This is especially useful for free tier APIs.

### How It Works

When a rate limit is encountered:
1. System detects the 429 error
2. Waits with exponential backoff (1s, 2s, 4s, 8s, ...)
3. Retries up to 5 times (configurable)
4. Adds random jitter to avoid thundering herd

### Example Output

```
⚠️  Rate limit error: 429 You exceeded your current quota
   Retrying in 2.3s... (attempt 1/5)
```

### Default Configuration

Retry behavior is controlled by `Config` (or environment variables):

- `RETRY_MAX_ATTEMPTS` (default: 3)
- `RETRY_INITIAL_DELAY` (default: 1.0s)
- `RETRY_MAX_DELAY` (default: 60.0s)
- `RETRY_EXPONENTIAL_BASE` (default: 2.0)
- `RETRY_JITTER` (default: true)

### Custom Retry Configuration

For APIs with strict rate limits:

```python
from llm import LiteLLMAdapter
from config import Config

Config.RETRY_MAX_ATTEMPTS = 10
Config.RETRY_INITIAL_DELAY = 2.0
Config.RETRY_MAX_DELAY = 120.0
Config.RETRY_EXPONENTIAL_BASE = 2.0
Config.RETRY_JITTER = True

llm = LiteLLMAdapter(model="gemini/gemini-1.5-flash", api_key="your_key")
```

### Backoff Calculation

The delay between retries is calculated as:

```python
delay = min(initial_delay * (exponential_base ** attempt), max_delay)

# With jitter:
actual_delay = delay * random.uniform(0.75, 1.25)
```

**Example progression** (initial_delay=1.0, base=2.0):
- Attempt 1: 1.0s (±25%)
- Attempt 2: 2.0s (±25%)
- Attempt 3: 4.0s (±25%)
- Attempt 4: 8.0s (±25%)
- Attempt 5: 16.0s (±25%)

## Memory Management System

The memory management system optimizes token usage for long-running tasks.

### Quick Start

Enable in `.env`:

```bash
MEMORY_ENABLED=true
MEMORY_COMPRESSION_THRESHOLD=40000
```

### How It Works

1. **Short-Term Memory**: Keeps recent N messages in full fidelity
2. **Compression**: When threshold is exceeded, old messages are summarized
3. **Token Tracking**: Monitors usage and calculates costs
4. **Automatic Optimization**: Compresses transparently during execution

### Memory Statistics

At the end of execution:

```
--- Memory Statistics ---
Total tokens: 45000
Compressions: 3
Net savings: 15000 tokens (33.3%)
Total cost: $0.0234
```

### Compression Strategies

**1. Sliding Window** (default):
```bash
MEMORY_COMPRESSION_STRATEGY=sliding_window
```
- Summarizes all old messages into compact summary
- Best for: Long conversations where context matters
- Savings: 60-70%

**2. Selective**:
```bash
MEMORY_COMPRESSION_STRATEGY=selective
```
- Preserves important messages (tool calls, errors)
- Summarizes less important content
- Best for: Critical intermediate results
- Savings: 40-50%

**3. Deletion**:
```bash
MEMORY_COMPRESSION_STRATEGY=deletion
```
- Simply drops old messages
- Best for: Tasks where old context isn't needed
- Savings: 100% (most aggressive)

### Token Tracking

Track costs across providers:

```python
from memory import MemoryManager, MemoryConfig

config = MemoryConfig(enable_compression=True)
memory = MemoryManager(config, llm)

# ... use memory ...

# Get statistics
stats = memory.get_stats()
print(f"Total cost: ${stats['total_cost']:.4f}")
print(f"Tokens saved: {stats['net_savings']}")
```

See [Memory Management](memory-management.md) for complete documentation.

## Multi-Provider Support

### Switching Providers

Easy switching between LLM providers:

```python
from llm import LiteLLMAdapter

# Anthropic
llm = LiteLLMAdapter(model="anthropic/claude-3-5-sonnet-20241022", api_key=api_key)

# OpenAI
llm = LiteLLMAdapter(model="openai/gpt-4o", api_key=api_key)

# Gemini
llm = LiteLLMAdapter(model="gemini/gemini-1.5-pro", api_key=api_key)
```

### Provider Comparison

| Provider | Best For | Strengths | Cost |
|----------|----------|-----------|------|
| **Anthropic** | Long context, reasoning | Large context window, thoughtful responses | Medium |
| **OpenAI** | General purpose | Well-documented, reliable | Medium-High |
| **Gemini** | Cost optimization | Fast, cheap, good free tier | Low |

### Hybrid Approach

Use different providers for different tasks:

```python
# Expensive model for planning
planning_llm = LiteLLMAdapter(model="anthropic/claude-3-opus-20240229", api_key=key)
planner = PlanExecuteAgent(llm=planning_llm)
plan = planner._get_plan(task)

# Cheap model for execution
execution_llm = LiteLLMAdapter(model="gemini/gemini-1.5-flash", api_key=key)
executor = ReActAgent(llm=execution_llm)
results = [executor.run(step) for step in plan]
```

## Custom Base URLs

Support for proxies, Azure, and local deployments:

### Configuration

```bash
# Proxy / custom endpoint
LITELLM_API_BASE=http://proxy.company.com
```

### Use Cases

1. **Corporate Proxies**: Route through company infrastructure
2. **Azure OpenAI**: Use Azure-hosted models
3. **Local Models**: Point to local LLM servers
4. **Caching Layers**: Add caching proxy in front
5. **Cost Tracking**: Route through usage tracking proxy

### Example: Azure OpenAI

```bash
# .env
LITELLM_MODEL=azure/gpt-4
AZURE_API_KEY=your_azure_key
AZURE_API_BASE=https://your-resource.openai.azure.com
AZURE_API_VERSION=2024-02-15-preview
```

## Agent Mode Comparison

### ReAct Mode

**Best for:**
- Interactive problem-solving
- Tasks requiring flexible strategy adjustment
- Debugging and exploration

**Characteristics:**
- Iterative think-act-observe loop
- Adapts strategy based on results
- More token-efficient for simple tasks

**When to use:**
- Task requirements unclear
- Need to adjust approach based on findings
- Debugging or exploration needed

### Plan-Execute Mode

**Best for:**
- Complex multi-step tasks
- Tasks benefiting from upfront planning
- Structured workflows

**Characteristics:**
- Creates complete plan first
- Executes steps sequentially
- Better for tasks with clear structure

**When to use:**
- Task has obvious steps
- Need structured approach
- Want to review plan before execution

### Choosing the Right Mode

| Task Type | Recommended Mode | Reason |
|-----------|-----------------|---------|
| "Calculate X" | ReAct | Simple, direct |
| "Research and summarize" | Plan-Execute | Multi-step, structured |
| "Debug this error" | ReAct | Exploratory |
| "Analyze data and report" | Plan-Execute | Clear workflow |
| "Find and fix issues" | ReAct | Iterative discovery |

## Performance Optimization

### 1. Model Selection

Choose the right model for the task:

```python
# Simple tasks - use fast, cheap models
if task_complexity == "simple":
    model = "gpt-4o-mini"  # or gemini-1.5-flash

# Complex reasoning - use capable models
elif task_complexity == "complex":
    model = "claude-3-5-sonnet-20241022"

# Critical tasks - use best models
elif task_complexity == "critical":
    model = "claude-3-opus-20240229"
```

### 2. Iteration Limits

Tune max iterations based on task:

```python
# Simple calculation
agent = ReActAgent(llm=llm, max_iterations=3)

# Normal task
agent = ReActAgent(llm=llm, max_iterations=10)

# Complex research
agent = ReActAgent(llm=llm, max_iterations=20)
```

### 3. Tool Selection

Only provide relevant tools:

```python
# For file operations only
tools = [FileReadTool(), FileWriteTool(), FileSearchTool()]

# For calculations only
tools = [CalculatorTool()]

# For web research
tools = [WebSearchTool(), FileWriteTool()]
```

Fewer tools = clearer LLM decisions = faster execution

### 4. Memory Tuning

Optimize memory settings:

```bash
# For long conversations (100+ messages)
MEMORY_ENABLED=true
MEMORY_COMPRESSION_THRESHOLD=40000

# For short tasks (< 20 messages)
MEMORY_ENABLED=false

# For medium tasks (20-50 messages)
MEMORY_ENABLED=true
MEMORY_COMPRESSION_THRESHOLD=60000  # Less aggressive
```

## Cost Optimization

### Strategy 1: Model Tiering

Use different models by task complexity:

```python
def get_optimal_llm(task_type: str):
    if task_type == "simple":
        return LiteLLMAdapter(model="gemini/gemini-1.5-flash", api_key=key)
    elif task_type == "medium":
        return LiteLLMAdapter(model="openai/gpt-4o-mini", api_key=key)
    else:
        return LiteLLMAdapter(model="anthropic/claude-3-5-sonnet-20241022", api_key=key)
```

### Strategy 2: Memory Compression

Enable aggressive compression:

```bash
MEMORY_ENABLED=true
MEMORY_COMPRESSION_THRESHOLD=30000  # Compress earlier
MEMORY_COMPRESSION_RATIO=0.2  # More aggressive (20% of original)
```

### Strategy 3: Iteration Limits

Prevent runaway costs:

```bash
MAX_ITERATIONS=8  # Lower limit
```

### Strategy 4: Prompt Optimization

Shorter, clearer prompts:

```python
# Bad: Verbose prompt
"Please analyze this file and provide a comprehensive detailed report..."

# Good: Concise prompt
"Analyze file and list key findings"
```

### Cost Comparison

Estimated costs for a 50-iteration task:

| Configuration | Estimated Cost |
|--------------|---------------|
| GPT-4o, no memory | $0.50 |
| GPT-4o, with memory | $0.20 |
| GPT-4o-mini, with memory | $0.03 |
| Gemini Flash, with memory | $0.01 |

## Error Handling

### Graceful Degradation

```python
from llm import LiteLLMAdapter

try:
    llm = LiteLLMAdapter(model="anthropic/claude-3-5-sonnet-20241022", api_key=api_key)
except Exception as e:
    print(f"Failed to initialize Anthropic, falling back to OpenAI")
    llm = LiteLLMAdapter(model="openai/gpt-4o-mini", api_key=api_key)
```

### Timeout Handling

```python
import signal

def timeout_handler(signum, frame):
    raise TimeoutError("Agent execution exceeded time limit")

# Set 5-minute timeout
signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(300)

try:
    result = await agent.run(task)
finally:
    signal.alarm(0)  # Cancel alarm
```

### Rate Limit Strategies

**Strategy 1**: Automatic retry (built-in)
```python
llm = LiteLLMAdapter(model=f"{provider}/{model}", api_key=key)  # Auto-retry enabled
```

**Strategy 2**: Provider fallback
```python
try:
    llm = LiteLLMAdapter(model=f"anthropic/{model1}", api_key=key1)
    result = await agent.run(task)
except RateLimitError:
    llm = LiteLLMAdapter(model=f"openai/{model2}", api_key=key2)
    result = await agent.run(task)
```

**Strategy 3**: Request throttling
```python
import asyncio

for task in tasks:
    result = await agent.run(task)
    await asyncio.sleep(1)  # Rate limit to 60/minute
```

## Debugging and Monitoring

### Enable Verbose Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("agentic_loop")

# Now you'll see detailed logs
await agent.run(task)
```

### Track Metrics

```python
from time import time

start = time()
result = await agent.run(task)
duration = time() - start

stats = agent.memory.get_stats()
print(f"Duration: {duration:.2f}s")
print(f"Tokens: {stats['current_tokens']}")
print(f"Cost: ${stats['total_cost']:.4f}")
```

### Custom Callbacks

```python
from time import time

class MonitoredAgent(ReActAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.metrics = []

    async def _call_llm(self, messages, tools=None):
        start = time()
        response = await super()._call_llm(messages, tools)
        duration = time() - start

        self.metrics.append({
            "timestamp": time(),
            "duration": duration,
            "tokens": len(str(messages))
        })

        return response
```

## Best Practices

1. **Start Simple**: Begin with default settings, optimize later
2. **Monitor Costs**: Track token usage and costs during development
3. **Use Memory**: Enable for tasks with > 20 messages
4. **Choose Right Mode**: ReAct for exploration, Plan-Execute for structure
5. **Tune Models**: Use cheaper models for simple tasks
6. **Set Limits**: Always configure `MAX_ITERATIONS`
7. **Handle Errors**: Implement fallbacks for rate limits
8. **Test Incrementally**: Test with small tasks first

## Common Patterns

### Pattern 1: Research Pipeline

```python
# 1. Use Gemini Flash for initial search (cheap)
search_llm = LiteLLMAdapter(model="gemini/gemini-1.5-flash", api_key=key)
searcher = ReActAgent(llm=search_llm, max_iterations=5)
raw_data = await searcher.run("Search for X")

# 2. Use Claude Sonnet for analysis (quality)
analysis_llm = LiteLLMAdapter(model="anthropic/claude-3-5-sonnet-20241022", api_key=key)
analyzer = PlanExecuteAgent(llm=analysis_llm)
final_report = await analyzer.run(f"Analyze this data: {raw_data}")
```

### Pattern 2: Batch Processing with Rate Limiting

```python
import asyncio

results = []
for i, task in enumerate(tasks):
    result = await agent.run(task)
    results.append(result)

    # Add delay every 10 requests
    if (i + 1) % 10 == 0:
        print("Rate limiting... waiting 60s")
        await asyncio.sleep(60)
```

### Pattern 3: Progressive Enhancement

```python
# Try with cheap model first
try:
    cheap_llm = LiteLLMAdapter(model="gemini/gemini-1.5-flash", api_key=key)
    agent = ReActAgent(llm=cheap_llm, max_iterations=5)
    result = await agent.run(task)

    # If result is low quality, retry with better model
    if not is_good_quality(result):
        raise ValueError("Quality too low")

except (ValueError, Exception):
    print("Retrying with better model...")
    better_llm = LiteLLMAdapter(model="anthropic/claude-3-5-sonnet-20241022", api_key=key)
    agent = ReActAgent(llm=better_llm, max_iterations=10)
    result = await agent.run(task)
```

## Next Steps

- See [Configuration](configuration.md) for detailed settings
- See [Memory Management](memory-management.md) for memory optimization
- See [Extending](extending.md) to build custom features
