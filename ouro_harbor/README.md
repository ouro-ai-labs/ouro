# Ouro Harbor Integration

[Harbor](https://github.com/laude-institute/harbor) integration for evaluating ouro on agent benchmarks (e.g. [Terminal-Bench 2.0](https://github.com/laude-institute/terminal-bench-2)).

## Prerequisites

- Python 3.12+
- Docker (Harbor runs agents inside containers)
- An LLM API key (e.g. `OURO_API_KEY`)

## Setup

1. Install Harbor:

```bash
pip install harbor
```

2. Install ouro with the Harbor extra (from the repo root):

```bash
pip install -e ".[harbor]"
```

## Running Benchmarks

### Basic Usage

```bash
export OURO_API_KEY=<your-api-key>

harbor run \
  --agent-import-path ouro_harbor.ouro_agent:OuroAgent \
  --model anthropic/claude-sonnet-4-5-20250929 \
  --dataset terminal-bench@2.0
```

### Common Options

| Flag | Description |
|------|-------------|
| `--model ID` | LiteLLM model ID (e.g. `anthropic/claude-sonnet-4-5-20250929`, `openai/gpt-4o`) |
| `--dataset NAME` | Benchmark dataset (e.g. `terminal-bench@2.0`) |
| `--n-tasks N` / `-l N` | Limit to N tasks |
| `--n-concurrent N` | Run N trials in parallel |
| `--task-path PATH` | Run a specific task by path |

### Examples

Run a single specific task:

```bash
harbor run \
  --agent-import-path ouro_harbor.ouro_agent:OuroAgent \
  --model anthropic/claude-sonnet-4-5-20250929 \
  --dataset terminal-bench@2.0 \
  --task-path gpt2-codegolf \
  -l 1
```

Run 10 tasks with 4 concurrent workers:

```bash
harbor run \
  --agent-import-path ouro_harbor.ouro_agent:OuroAgent \
  --model openai/gpt-4o \
  --dataset terminal-bench@2.0 \
  -l 10 --n-concurrent 4
```

Use a custom API endpoint:

```bash
export OURO_API_KEY=<key>
export OURO_BASE_URL=https://your-proxy.example.com/v1

harbor run \
  --agent-import-path ouro_harbor.ouro_agent:OuroAgent \
  --model anthropic/claude-sonnet-4-5-20250929 \
  --dataset terminal-bench@2.0
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OURO_API_KEY` | API key passed to the model provider |
| `OURO_BASE_URL` | Custom API base URL (optional) |
| `OURO_TIMEOUT` | LLM request timeout in seconds (default: `600`) |

## How It Works

1. **Install phase**: Harbor builds a Docker container and runs `install-ouro.sh.j2` to install ouro via `uv tool install`.
2. **Setup phase**: A `~/.ouro/models.yaml` is written inside the container with the model config derived from `--model` and the environment variables above.
3. **Run phase**: `ouro --model <model> --task "<instruction>"` is executed. Output is captured to `/logs/agent/ouro-output.txt` and session files are copied to `/logs/agent/sessions/`.
4. **Verify phase**: Harbor's verifier checks the agent's work and assigns a reward score.

## Debugging

Trial results are saved under `jobs/<timestamp>/<trial-name>/`. Key files:

```
jobs/
└── 2026-02-09__22-08-12/
    └── gpt2-codegolf__eAFdbtU/
        ├── result.json                      # Final result + reward
        ├── agent/
        │   ├── command-0/stdout.txt         # Setup command output
        │   ├── command-1/stdout.txt         # Run command output
        │   └── sessions/                    # Ouro session YAML files
        └── ...
```

To inspect a session trace:

```bash
cat jobs/<timestamp>/<trial>/agent/sessions/<date>_<id>/session.yaml
```
