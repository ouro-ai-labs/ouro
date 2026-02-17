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
Login uses a browser-based OAuth (PKCE) flow with a localhost callback server. If browser auto-open fails, ouro prints a URL you can open manually (for remote machines, SSH port-forwarding may be required).
Advanced OAuth overrides (rarely needed) are documented in `docs/configuration.md`.

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
| `--verify` | | Enable self-verification (Ralph Loop) in `--task` mode |
| `--reasoning-effort LEVEL` | - | Set run-scoped reasoning effort (`default|none|minimal|low|medium|high|xhigh|off`) |
| `--verbose` | `-v` | Enable verbose logging to `~/.ouro/logs/` |

## Interactive Commands

### Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/reset` | Clear conversation and start fresh |
| `/stats` | Show memory and token usage statistics |
| `/resume [id]` | List or resume a previous session |
| `/model` | Pick a model (arrow keys + Enter) |
| `/model edit` | Open `~/.ouro/models.yaml` in editor (auto-reload on save) |
| `/login` | Open OAuth provider selector and login |
| `/logout` | Open OAuth provider selector and logout |
| `/theme` | Toggle dark/light theme |
| `/verbose` | Toggle thinking display |
| `/reasoning` | Open reasoning menu |
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
- **Self-verification**: Ralph Loop verifies the agent's answer against the original task and re-enters if incomplete (`--verify`)
- **Parallel execution**: Concurrent readonly tool calls in a single turn, plus `multi_task` for spawning parallel sub-agents with dependency ordering
- **Memory system**: LLM-driven compression (sliding window / selective / deletion), git-aware long-term memory, and YAML session persistence resumable via `--resume`
- **OAuth login**: `--login` / `/login` to authenticate with ChatGPT Codex subscription models; bundled OAuth catalog auto-synced
- **TUI**: Dark/light themes, slash-command autocomplete, live status bar, token & cache tracking (`/stats`)
- **Skills**: Extensible skill registry — list, install, and manage via `/skills`
- **Benchmarks**: First-class [Harbor](https://github.com/laude-institute/harbor) integration for agent evaluation (see [Evaluation](#evaluation))

## Evaluation

Ouro can be evaluated on agent benchmarks using [Harbor](https://github.com/laude-institute/harbor). A convenience script `harbor-run.sh` is provided at the repo root:

1. Edit `harbor-run.sh` to set your model, dataset, and ouro version.
2. Run:

```bash
export OURO_API_KEY=<your-api-key>
./harbor-run.sh                    # run with defaults in the script
./harbor-run.sh -l 5               # limit to 5 tasks
./harbor-run.sh --n-concurrent 4   # 4 parallel workers
```

Extra flags are forwarded to `harbor run`, so any Harbor CLI option works. See [ouro_harbor/README.md](ouro_harbor/README.md) for full details.

## Configuration

See [Configuration Guide](docs/configuration.md) for all settings.

## Documentation

- [Configuration](docs/configuration.md) -- model setup, runtime settings, custom endpoints
- [Examples](docs/examples.md) -- usage patterns and programmatic API
- [Memory Management](docs/memory-management.md) -- compression, persistence, token tracking
- [Extending](docs/extending.md) -- adding tools, agents, LLM providers
- [Packaging](docs/packaging.md) -- building, publishing, Docker

## Contributing

Contributions are welcome! Please open an [issue](https://github.com/ouro-ai-labs/ouro/issues) or submit a pull request.

For development setup, see the [Installation](#installation) section (install from source).

## License

MIT License
