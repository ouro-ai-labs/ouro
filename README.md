<div align="center">

<img alt="OURO" src="docs/assets/logo.png" width="440">

[![PyPI](https://img.shields.io/pypi/v/ouro-ai)](https://pypi.org/project/ouro-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)]()

*An open-source AI agent — run it as a Coding agent CLI or deploy it as a bot just like JARVIS.*

</div>

Ouro is derived from Ouroboros—the ancient symbol of a serpent consuming its own tail to form a perfect circle. It represents the ultimate cycle: a closed loop of self-consumption, constant renewal, and infinite iteration.

At Ouro AI Lab, this is our blueprint. We are building the next generation of AI agents capable of autonomous evolution—systems that learn from their own outputs, refine their own logic, and achieve a state of infinite self-improvement.

## Two Modes, One Agent

Ouro ships with a unified agent core and two deployment modes:

| | **CLI Mode** | **Bot Mode** |
|---|---|---|
| **What** | Interactive REPL + one-shot task execution | Persistent IM assistant (Lark, Slack) |
| **Install** | `pip install ouro-ai` | `pip install ouro-ai[bot]` |
| **Run** | `ouro` | `ouro --bot` |
| **Guide** | [CLI Guide](docs/cli-guide.md) | [Bot Guide](docs/bot-guide.md) |

## Quick Start

Prerequisites: Python 3.12+.

```bash
pip install ouro-ai
```

On first run, `~/.ouro/models.yaml` is created. Add your API key:

```yaml
models:
  openai/gpt-4o:
    api_key: sk-...
default: openai/gpt-4o
current: openai/gpt-4o
```

Then run:

```bash
# Interactive mode
ouro

# Single task
ouro --task "Calculate 123 * 456"

# Bot mode (requires ouro-ai[bot])
ouro --bot
```

See [LiteLLM Providers](https://docs.litellm.ai/docs/providers) for the full provider list.

## Features

- **Dual mode**: Interactive CLI with rich TUI + persistent IM bot (Lark, Slack) — same agent core, two deployment modes
- **Unified agent loop**: Think-Act-Observe cycle — planning, sub-agents, and tool use all happen in one loop
- **Self-verification**: Ralph Loop verifies the agent's answer against the original task and re-enters if incomplete (`--verify`)
- **Parallel execution**: Concurrent readonly tool calls in a single turn, plus `multi_task` for spawning parallel sub-agents with dependency ordering
- **Memory system**: LLM-driven compression, long-term memory, and YAML session persistence resumable across restarts
- **Proactive mechanisms**: Heartbeat self-checks + cron-scheduled tasks, with results broadcast to active IM sessions
- **Personality**: Customizable soul file (`~/.ouro/bot/soul.md`) defines bot identity and tone
- **Skills**: Extensible skill registry — dynamically loaded per session
- **OAuth login**: `--login` / `/login` to authenticate with ChatGPT Codex subscription models
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

## Documentation

- **[CLI Guide](docs/cli-guide.md)** -- interactive mode, task mode, commands, shortcuts
- **[Bot Guide](docs/bot-guide.md)** -- IM bot setup, commands, proactive mechanisms, personality
- [JSONL Protocol](docs/protocol-jsonl.md) -- event schema contracts and reserved input channel
- [Configuration](docs/configuration.md) -- model setup, runtime settings, custom endpoints
- [Examples](docs/examples.md) -- usage patterns and programmatic API
- [Memory Management](docs/memory-management.md) -- compression, persistence, token tracking
- [Extending](docs/extending.md) -- adding tools, agents, LLM providers
- [Packaging](docs/packaging.md) -- building, publishing, Docker

## Contributing

Contributions are welcome! Please open an [issue](https://github.com/ouro-ai-labs/ouro/issues) or submit a pull request.

For development setup, see the [Quick Start](#quick-start) section (install from source):

```bash
git clone https://github.com/ouro-ai-labs/ouro.git
cd ouro
./scripts/bootstrap.sh   # requires uv
```

## License

MIT License
