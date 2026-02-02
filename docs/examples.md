# Examples

## Single Task Mode

Run a task and exit. The `--task` flag outputs the raw result only (no TUI chrome).

```bash
# Simple calculation
aloop --task "Calculate the first 10 digits of pi"

# File operations
aloop --task "Create a file hello.txt with content 'Hello, Agent!'"
aloop --task "Read data.csv and count the number of rows"

# Web search
aloop --task "Search for the latest news about AI agents"

# Shell
aloop --task "List all Python files in the current directory"
aloop --task "Check git status and show recent commits"

# Code generation
aloop --task "Write a Python script to calculate fibonacci numbers and save it to fib.py"

# Specify model
aloop --task "Summarize this README" --model openai/gpt-4o
```

From source (without install):

```bash
python main.py --task "Calculate 1+1"
```

## Interactive Mode

Start without `--task` to enter interactive mode:

```bash
aloop
```

Type your request and press Enter twice to submit. The agent will think, use tools, and respond.

### Slash Commands

```
/help                    Show available commands
/stats                   Show token usage and cost
/model                   Pick a different model
/model edit              Edit ~/.aloop/models.yaml in your editor
/theme                   Toggle dark/light theme
/verbose                 Toggle thinking display
/compact                 Toggle compact output
/clear                   Clear conversation and start fresh
/resume                  List recent sessions
/resume a1b2c3d4         Resume session by ID prefix
/exit                    Exit
```

### Keyboard Shortcuts

- `/` triggers command autocomplete
- `Ctrl+C` cancels the current operation
- `Ctrl+L` clears the screen
- `Ctrl+T` toggles thinking display
- `Ctrl+S` shows quick stats
- Up/Down arrows navigate command history

## Session Resume

Sessions are automatically saved. Resume with the CLI or interactively:

```bash
# Resume most recent session
aloop --resume

# Resume by session ID prefix
aloop --resume a1b2c3d4

# Resume and continue with a new task
aloop --resume a1b2c3d4 --task "Continue the analysis"
```

In interactive mode:
```
/resume                  # Shows recent sessions to pick from
/resume a1b2c3d4         # Directly resume by prefix
```

## Tool Usage

The agent automatically selects tools based on the task. Some examples of what the tools enable:

**File operations**:
```bash
aloop --task "Read all .txt files in ./data and create a summary"
aloop --task "Find all TODO comments in Python files"
```

**Web search and fetch**:
```bash
aloop --task "Search for Python 3.12 new features and summarize"
aloop --task "Fetch https://example.com and extract the main content"
```

**Shell commands**:
```bash
aloop --task "Show disk usage and available space"
aloop --task "Run pytest and summarize the results"
```

**Code navigation** (tree-sitter AST):
```bash
aloop --task "List all classes and functions in src/"
```

## Programmatic Usage

```python
import asyncio
from agent.agent import LoopAgent
from llm import LiteLLMAdapter, ModelManager
from tools.file_ops import FileReadTool
from tools.shell import ShellTool

async def main():
    mm = ModelManager()
    profile = mm.get_current_model()
    if not profile:
        raise RuntimeError("No models configured. Edit ~/.aloop/models.yaml.")

    llm = LiteLLMAdapter(
        model=profile.model_id,
        api_key=profile.api_key,
        api_base=profile.api_base,
    )

    agent = LoopAgent(
        llm=llm,
        max_iterations=15,
        tools=[ShellTool(), FileReadTool()],
    )

    result = await agent.run("Calculate 2^100 using python")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
```

## Troubleshooting

**Task not completing**: Increase `MAX_ITERATIONS` in `~/.aloop/config` (default: 1000).

**High token usage**: Memory compression is enabled by default. Adjust `MEMORY_COMPRESSION_THRESHOLD` in `~/.aloop/config` to trigger compression earlier. Switch to a cheaper model with `--model` or `/model`.

**API errors**: Verify your API key in `~/.aloop/models.yaml`. Test with a simple task: `aloop --task "Calculate 1+1"`.

**Rate limits**: Automatic retry with exponential backoff is built in. Configure `RETRY_MAX_ATTEMPTS` in `~/.aloop/config` (default: 3).

**Verbose output for debugging**: Use `--verbose` to log detailed info to `~/.aloop/logs/`.
