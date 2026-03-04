# CLI Mode Guide

Ouro's CLI mode gives you a coding agent right in your terminal — interactive REPL or one-shot task execution.

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

## Configure Models

On first run, `~/.ouro/models.yaml` is created with a template. Edit it to add your provider and API key:

```yaml
models:
  openai/gpt-4o:
    api_key: sk-...

  anthropic/claude-sonnet-4:
    api_key: sk-ant-...

  chatgpt/gpt-5.2-codex:
    timeout: 600

  ollama/llama2:
    api_base: http://localhost:11434

default: openai/gpt-4o
current: openai/gpt-4o
```

For `chatgpt/*` subscription models, run `ouro --login` (or `/login` in interactive mode) and select provider before use.
OAuth models shown in `/model` are seeded from ouro's bundled catalog (synced from pi-ai `openai-codex` model list).
Login uses a browser-based OAuth (PKCE) flow with a localhost callback server. If browser auto-open fails, ouro prints a URL you can open manually (for remote machines, SSH port-forwarding may be required).

See [LiteLLM Providers](https://docs.litellm.ai/docs/providers) for the full list. For advanced OAuth overrides, see [Configuration](configuration.md).

## Usage

```bash
# Interactive mode (REPL)
ouro

# Single task (returns raw result)
ouro --task "Calculate 123 * 456"

# Resume last session
ouro --resume

# Resume specific session (ID prefix)
ouro --resume a1b2c3d4
```

## CLI Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--task TEXT` | `-t` | Run a single task and exit |
| `--model ID` | `-m` | LiteLLM model ID to use |
| `--resume [ID]` | `-r` | Resume a session (`latest` if no ID given) |
| `--login` | - | Open OAuth provider selector and login |
| `--logout` | - | Open OAuth provider selector and logout |
| `--verify` | | Enable self-verification (Ralph Loop) in `--task` mode |
| `--reasoning-effort LEVEL` | - | Set run-scoped reasoning effort (`default|none|minimal|low|medium|high|xhigh|off`) |
| `--input-events PATH` | - | Reserved `input_event` NDJSON channel path (currently no-op) |
| `--verbose` | `-v` | Enable verbose logging to `~/.ouro/logs/` |

`--input-events` reserves CLI surface for future orchestrator-driven inbound protocol events. In current releases it is intentionally ignored to preserve existing single-run behavior.

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
