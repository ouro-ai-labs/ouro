# Examples

## Single Task Mode

Run a task and exit. The `--task` flag outputs the raw result only (no TUI chrome).

```bash
# Simple calculation
ouro --task "Calculate the first 10 digits of pi"

# File operations
ouro --task "Create a file hello.txt with content 'Hello, Agent!'"
ouro --task "Read data.csv and count the number of rows"

# Web search
ouro --task "Search for the latest news about AI agents"

# Shell
ouro --task "List all Python files in the current directory"
ouro --task "Check git status and show recent commits"

# Code generation
ouro --task "Write a Python script to calculate fibonacci numbers and save it to fib.py"

# Specify model
ouro --task "Summarize this README" --model openai/gpt-4o
```

From source (without install):

```bash
python main.py --task "Calculate 1+1"
```

## ChatGPT / Codex Login

```bash
# Login (select provider from menu)
ouro --login

# Logout (select provider from menu)
ouro --logout

# If browser does not open automatically, use this URL manually:
# https://auth.openai.com/codex/device
```

## Interactive Mode

Start without `--task` to enter interactive mode:

```bash
ouro
```

Type your request and press Enter twice to submit. The agent will think, use tools, and respond.

### Slash Commands

```
/help                    Show available commands
/stats                   Show token usage and cost
/model                   Pick a different model
/model edit              Edit ~/.ouro/models.yaml in your editor
/login                   Login to OAuth provider (menu)
/logout                  Logout from OAuth provider (menu)
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
ouro --resume

# Resume by session ID prefix
ouro --resume a1b2c3d4

# Resume and continue with a new task
ouro --resume a1b2c3d4 --task "Continue the analysis"
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
ouro --task "Read all .txt files in ./data and create a summary"
ouro --task "Find all TODO comments in Python files"
```

**Web search and fetch**:
```bash
ouro --task "Search for Python 3.12 new features and summarize"
ouro --task "Fetch https://example.com and extract the main content"
```

**Shell commands**:
```bash
ouro --task "Show disk usage and available space"
ouro --task "Run pytest and summarize the results"
```

**Code navigation** (tree-sitter AST):
```bash
ouro --task "List all classes and functions in src/"
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
        raise RuntimeError("No models configured. Edit ~/.ouro/models.yaml.")

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

**Task not completing**: Increase `MAX_ITERATIONS` in `~/.ouro/config` (default: 1000).

**High token usage**: Memory compression is enabled by default. Adjust `MEMORY_COMPRESSION_THRESHOLD` in `~/.ouro/config` to trigger compression earlier. Switch to a cheaper model with `--model` or `/model`.

**API errors**: Verify your API key in `~/.ouro/models.yaml`. Test with a simple task: `ouro --task "Calculate 1+1"`.

**Rate limits**: Automatic retry with exponential backoff is built in. Configure `RETRY_MAX_ATTEMPTS` in `~/.ouro/config` (default: 3).

**Verbose output for debugging**: Use `--verbose` to log detailed info to `~/.ouro/logs/`.
