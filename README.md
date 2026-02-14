<div align="center">

<img alt="OURO" src="docs/assets/logo.png" width="440">

[![PyPI](https://img.shields.io/pypi/v/ouro-ai)](https://pypi.org/project/ouro-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)]()

*An open-source AI agent built on a single, unified loop.*

</div>

Ouro is derived from Ouroboros—the ancient symbol of a serpent consuming its own tail to form a perfect circle. It represents the ultimate cycle: a closed loop of self-consumption, constant renewal, and infinite iteration.

At Ouro AI Lab, this is our blueprint. We are building the next generation of AI agents capable of autonomous evolution—systems that learn from their own outputs, refine their own logic, and achieve a state of infinite self-improvement.

## Installation

Prerequisites: Python 3.12+.

```bash
pip install ouro-ai
```

Or install from source (for development):

```bash
git clone https://github.com/ouro-ai-labs/ouro.git
cd ouro
./scripts/bootstrap.sh   # requires uv
```

## Quick Start

### 1. Configure Models

On first run, `~/.ouro/models.yaml` is created with a template. Edit it to add your provider and API key:

```yaml
models:
  openai/gpt-4o:
    api_key: sk-...

  anthropic/claude-sonnet-4:
    api_key: sk-ant-...

  chatgpt/gpt-5.3-codex:
    timeout: 600

  ollama/llama2:
    api_base: http://localhost:11434

default: openai/gpt-4o
```

For `chatgpt/*` subscription models, run `ouro --login` (or `/login` in interactive mode) and select provider before use.
OAuth models shown in `/model` are seeded from ouro's bundled catalog (synced from pi-ai `openai-codex` model list).
Maintainer note: refresh this catalog via `python scripts/update_oauth_model_catalog.py`.
If browser auto-open is unavailable in your environment, manually open `https://auth.openai.com/codex/device` and enter the code shown in terminal. When existing token/refresh state is valid, login usually completes without opening a new browser page.

See [LiteLLM Providers](https://docs.litellm.ai/docs/providers) for the full list.

### 2. Run

```bash
# Interactive mode
ouro

# Single task (returns raw result)
ouro --task "Calculate 123 * 456"

# Resume last session
ouro --resume

# Resume specific session (ID prefix)
ouro --resume a1b2c3d4
```

## CLI Reference

| Flag | Short | Description |
|------|-------|-------------|
| `--task TEXT` | `-t` | Run a single task and exit |
| `--model ID` | `-m` | LiteLLM model ID to use |
| `--resume [ID]` | `-r` | Resume a session (`latest` if no ID given) |
| `--login` | - | Open OAuth provider selector and login |
| `--logout` | - | Open OAuth provider selector and logout |
| `--verbose` | `-v` | Enable verbose logging to `~/.ouro/logs/` |

## Interactive Commands

### Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/clear` | Clear conversation and start fresh |
| `/stats` | Show memory and token usage statistics |
| `/resume [id]` | List or resume a previous session |
| `/model` | Pick a model (arrow keys + Enter) |
| `/model edit` | Open `~/.ouro/models.yaml` in editor (auto-reload on save) |
| `/login` | Open OAuth provider selector and login |
| `/logout` | Open OAuth provider selector and logout |
| `/theme` | Toggle dark/light theme |
| `/verbose` | Toggle thinking display |
| `/compact` | Trigger memory compression and show token savings |
| `/exit` | Exit (also `/quit`) |

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `/` | Command autocomplete |
| `Ctrl+C` | Graceful interrupt (cancels current operation, rolls back incomplete memory) |
| `Ctrl+L` | Clear screen |
| `Ctrl+T` | Toggle thinking display |
| `Ctrl+S` | Show quick stats |
| Up/Down | Navigate command history |

## Features

- **Unified agent loop**: Think-Act-Observe cycle — planning, sub-agents, and tool use all happen in one loop, chosen autonomously by the agent
- **Self-verification**: An outer loop verifies the agent's answer against the original task and re-enters if incomplete
- **Memory compression**: LLM-driven summarization when context exceeds a token threshold, with multiple strategies (`sliding_window`, `selective`, `deletion`)
- **Git-aware memory**: Git-based memory system that persists and manages agent memory through version control
- **Session persistence**: Conversations saved as human-readable YAML files under `~/.ouro/sessions/`, resumable via `--resume` or `/resume`
- **Parallel exploration**: Concurrent tool calls for exploring codebases and gathering information in parallel
- **Parallel sub-agents**: Spawn multiple sub-agents to work on independent subtasks simultaneously

## Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents |
| `write_file` | Write content to a file |
| `search_files` | Search for files by name |
| `edit_file` | Exact string replacement in files |
| `smart_edit` | LLM-assisted file editing |
| `glob_files` | Glob pattern file matching |
| `grep_content` | Regex search in file contents |
| `calculate` | Evaluate expressions / run Python code |
| `shell` | Execute shell commands |
| `shell_task_status` | Check background shell task status |
| `web_search` | Web search (DuckDuckGo) |
| `web_fetch` | Fetch and extract web page content |
| `explore_context` | Explore project structure and context |
| `parallel_execute` | Run multiple tool calls in parallel |
| `notify` | Send email notifications (Resend) |
| `manage_todo_list` | Manage a task/todo list |

## Project Structure

```
ouro/
├── main.py                 # Entry point (argparse)
├── cli.py                  # CLI wrapper (`ouro` entry point)
├── interactive.py          # Interactive session, model setup, TUI
├── config.py               # Runtime config (~/.ouro/config)
├── agent/
│   ├── base.py             # BaseAgent (ReAct + Ralph loops)
│   ├── agent.py            # LoopAgent
│   ├── verification.py     # LLMVerifier for Ralph loop
│   ├── context.py          # Context injection (cwd, platform, date)
│   ├── tool_executor.py    # Tool execution engine
│   └── todo.py             # Todo list data structure
├── llm/
│   ├── litellm_adapter.py  # LiteLLM adapter (100+ providers)
│   ├── model_manager.py    # Model config from ~/.ouro/models.yaml
│   ├── retry.py            # Retry with exponential backoff
│   └── message_types.py    # LLMMessage, LLMResponse, ToolCall
├── memory/
│   ├── manager.py          # Memory orchestrator + persistence
│   ├── compressor.py       # LLM-driven compression
│   ├── short_term.py       # Short-term memory (sliding window)
│   ├── token_tracker.py    # Token counting + cost tracking
│   ├── types.py            # Core data structures
│   └── store/
│       └── yaml_file_memory_store.py  # YAML session persistence
├── tools/                  # 18 tool implementations
├── utils/
│   ├── tui/                # TUI components (input, themes, status bar)
│   ├── logger.py           # Logging setup
│   └── model_pricing.py    # Model pricing data
├── docs/                   # Documentation
├── test/                   # Tests
├── scripts/                # Dev scripts (bootstrap.sh, dev.sh)
└── rfc/                    # RFC design documents
```

## Configuration

Runtime settings live in `~/.ouro/config` (auto-created). Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_ITERATIONS` | `1000` | Maximum agent loop iterations |
| `TOOL_TIMEOUT` | `600` | Tool execution timeout (seconds) |
| `RALPH_LOOP_MAX_ITERATIONS` | `3` | Max verification attempts |
| `MEMORY_ENABLED` | `true` | Enable memory management |
| `MEMORY_COMPRESSION_THRESHOLD` | `60000` | Token threshold for compression |
| `MEMORY_SHORT_TERM_SIZE` | `100` | Messages kept at full fidelity |
| `RETRY_MAX_ATTEMPTS` | `3` | Rate-limit retry attempts |

See [Configuration Guide](docs/configuration.md) for all settings.

## Documentation

- [Configuration](docs/configuration.md) -- model setup, runtime settings, custom endpoints
- [Examples](docs/examples.md) -- usage patterns and programmatic API
- [Memory Management](docs/memory-management.md) -- compression, persistence, token tracking
- [Extending](docs/extending.md) -- adding tools, agents, LLM providers
- [Packaging](docs/packaging.md) -- building, publishing, Docker

## Evaluation

Ouro can be evaluated on agent benchmarks using [Harbor](https://github.com/laude-institute/harbor). See [ouro_harbor/README.md](ouro_harbor/README.md) for setup and usage instructions.

## Contributing

Contributions are welcome! Please open an [issue](https://github.com/ouro-ai-labs/ouro/issues) or submit a pull request.

For development setup, see the [Installation](#installation) section (install from source).

## License

MIT License
