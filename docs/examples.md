# Usage Examples

This document provides detailed examples of using the Agentic Loop system with different modes and configurations.

## Simple Calculation

Calculate mathematical expressions using the calculator tool:

```bash
python main.py --task "Calculate the first 10 digits of pi"
```

Expected output:
```
The first 10 digits of pi are: 3.141592653
```

## File Operations

### Creating Files

```bash
python main.py --task "Create a file hello.txt with content 'Hello, Agent!'"
```

### Reading and Processing Files

```bash
python main.py --task "Read data.csv and count the number of rows"
```

### Multi-File Operations

```bash
python main.py --mode plan --task "Read all .txt files in the current directory and create a summary file"
```

## Web Search and Research

### Simple Search

```bash
python main.py --task "Search for the latest news about AI agents"
```

### Research and Summarization

```bash
python main.py --mode plan --task "Search for AI agent information, summarize key concepts, and save to summary.txt"
```

This will:
1. Create a plan for the research task
2. Execute web searches
3. Extract key information
4. Create a comprehensive summary
5. Save results to a file

## Complex Multi-Step Tasks

### Data Analysis Workflow

```bash
python main.py --mode plan --task "Analyze data.csv file and generate a report with statistics"
```

### Code Generation and Execution

```bash
python main.py --task "Write a Python script to calculate fibonacci numbers and save it to fib.py"
```

## Interactive Mode

For interactive sessions where you want to enter tasks dynamically:

```bash
python main.py --mode react
```

Then enter your task:
```
What would you like me to help you with?
> Calculate 123 * 456 and write the result to result.txt
>
```
(Press Enter twice to submit)

## Using Different LLM Providers

### With OpenAI GPT

```bash
# Set in .aloop/config:
OPENAI_API_KEY=your_key_here
LITELLM_MODEL=openai/gpt-4o

# Run:
python main.py --task "Your task here"
```

### With Google Gemini

```bash
# Set in .aloop/config:
GEMINI_API_KEY=your_key_here
LITELLM_MODEL=gemini/gemini-1.5-flash

# Run:
python main.py --task "Your task here"
```

### With Anthropic Claude

```bash
# Set in .aloop/config:
ANTHROPIC_API_KEY=your_key_here
LITELLM_MODEL=anthropic/claude-3-5-sonnet-20241022

# Run:
python main.py --task "Your task here"
```

## Shell Tool Examples

### Listing Files

```bash
python main.py --task "List all Python files in the current directory"
```

### Git Operations

```bash
python main.py --task "Check git status and show recent commits"
```

### System Information

```bash
python main.py --task "Show disk usage and available space"
```

## Comparing ReAct vs Plan-Execute

### Same Task, Different Modes

**ReAct Mode** (iterative problem-solving):
```bash
python main.py --mode react --task "Find all TODO comments in Python files and list them"
```

ReAct will:
- Think about the approach
- Search for files
- Adjust strategy based on findings
- Iterate until complete

**Plan-Execute Mode** (structured approach):
```bash
python main.py --mode plan --task "Find all TODO comments in Python files and list them"
```

Plan-Execute will:
- Create a complete plan upfront
- Execute each step sequentially
- Synthesize results at the end

## Error Handling Examples

### Automatic Retry on Rate Limits

```bash
python main.py --task "Perform 100 calculations in sequence"
```

If you hit rate limits, you'll see:
```
⚠️  Rate limit error: 429 You exceeded your current quota
   Retrying in 2.3s... (attempt 1/5)
```

The system will automatically retry with exponential backoff.

### Handling Missing Tools

If a task requires a tool that's not available:

```bash
# Example:
python main.py --task "Run ls command"
```

## Memory Management Examples

For long-running tasks with many iterations:

```bash
# Enable memory management in .aloop/config:
MEMORY_ENABLED=true

# Run a complex task:
python main.py --mode react --task "Analyze all Python files, find patterns, and generate a detailed report"
```

You'll see memory statistics at the end:
```
--- Memory Statistics ---
Total tokens: 45000
Compressions: 3
Net savings: 15000 tokens
Total cost: $0.1234
```

See [Memory Management](memory-management.md) for more details.

## Advanced Programmatic Usage

### Custom Agent Configuration

```python
import asyncio

from agent.react_agent import ReActAgent
from llm import LiteLLMAdapter
from tools import CalculatorTool, FileReadTool
from config import Config

async def main():
    # Create custom LLM with retry config
    Config.RETRY_MAX_ATTEMPTS = 10
    Config.RETRY_INITIAL_DELAY = 2.0
    Config.RETRY_MAX_DELAY = 60.0

    llm = LiteLLMAdapter(
        model=Config.LITELLM_MODEL,
        api_base=Config.LITELLM_API_BASE,
        drop_params=Config.LITELLM_DROP_PARAMS,
        timeout=Config.LITELLM_TIMEOUT,
    )

    # Create agent with specific tools
    agent = ReActAgent(
        llm=llm,
        max_iterations=15,
        tools=[CalculatorTool(), FileReadTool()]
    )

    # Run task
    result = await agent.run("Your complex task here")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
```

### Custom Tool Creation

```python
from tools.base import BaseTool
from typing import Dict, Any

class CustomTool(BaseTool):
    @property
    def name(self) -> str:
        return "custom_tool"

    @property
    def description(self) -> str:
        return "Does something custom"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "param1": {
                "type": "string",
                "description": "Parameter description"
            }
        }

    async def execute(self, param1: str) -> str:
        # Your custom logic
        return f"Processed: {param1}"

# Use in agent
agent = ReActAgent(
    llm=llm,
    tools=[CustomTool()]
)
```

## Troubleshooting Common Issues

### Task Not Completing

If a task doesn't complete within max iterations:

```bash
# Increase max iterations in .aloop/config:
MAX_ITERATIONS=20

# Or pass it programmatically:
agent = ReActAgent(llm=llm, max_iterations=20)
```

### High Token Usage

For tasks consuming too many tokens:

```bash
# Enable memory compression in .aloop/config:
MEMORY_ENABLED=true
MEMORY_COMPRESSION_THRESHOLD=40000

# Use more efficient models:
LITELLM_MODEL=openai/gpt-4o-mini  # or gemini/gemini-1.5-flash, anthropic/claude-3-5-haiku-20241022
```

### API Errors

For consistent API errors:

```bash
# Check your API key configuration
grep API_KEY .aloop/config

# Test with a simple task first
python main.py --task "Calculate 1+1"

# Enable debug logging (if available)
DEBUG=true python main.py --task "Your task"
```
