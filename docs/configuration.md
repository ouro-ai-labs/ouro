# Configuration Guide

This repo uses YAML-based configuration for model management via `.aloop/models.yaml`.
Model settings are not read from environment variables; use `.aloop/models.yaml` only.

## Model Configuration

On first run, `.aloop/models.yaml` is created automatically with a template. Edit it to configure your LLM providers:

```bash
# Open the config file
$EDITOR .aloop/models.yaml
```

### YAML Configuration Format

```yaml
# Model Configuration
# This file is gitignored - do not commit to version control

models:
  anthropic/claude-3-5-sonnet-20241022:
    api_key: sk-ant-...
    timeout: 600
    drop_params: true

  openai/gpt-4o:
    api_key: sk-...
    timeout: 300

  ollama/llama2:
    api_base: http://localhost:11434

default: anthropic/claude-3-5-sonnet-20241022
```

### Configuration Fields

The model ID (LiteLLM `provider/model`) is the key under `models`.

| Field | Required | Description | Example |
|-------|----------|-------------|---------|
| `api_key` | Yes* | API key | `sk-ant-xxx` |
| `api_base` | No | Custom base URL for proxies | `https://custom.api.com` |
| `timeout` | No | Request timeout in seconds | `600` |
| `drop_params` | No | Drop unsupported params | `true` |

*Required for most providers except local ones like Ollama.

### Model Examples

```yaml
# Anthropic Claude
models:
  anthropic/claude-3-5-sonnet-20241022:
    api_key: sk-ant-...

# OpenAI GPT
models:
  openai/gpt-4o:
    api_key: sk-...

# Google Gemini
models:
  gemini/gemini-1.5-pro:
    api_key: ...

# Local Ollama (no API key needed)
models:
  ollama/llama2:
    api_base: http://localhost:11434
```

For the full list of providers/models, see: https://docs.litellm.ai/docs/providers

## Interactive Mode Commands

When running in interactive mode, you can manage models using the `/model` command:

### Pick Model (Cursor)
```bash
> /model
```
Pick a model with arrow keys and Enter (Esc to cancel).

### Edit Model Config
```bash
> /model edit
```
Open `.aloop/models.yaml` in your editor, then it will auto-reload after you save.

Add/remove/default are done by editing `.aloop/models.yaml` directly.

## Ralph Loop (Outer Verification)

An outer loop verifies that the agent's final answer actually satisfies
the original task. If incomplete, feedback is injected and the inner
ReAct loop re-enters. Enabled by default.

```bash
RALPH_LOOP_MAX_ITERATIONS=3    # Max verification attempts before returning
```

## Email Notification Configuration (Resend)

Used by the `notify` tool to send emails via [Resend](https://resend.com):

```bash
RESEND_API_KEY=re_xxxxxxxx
NOTIFY_EMAIL_FROM=AgenticLoop <onboarding@resend.dev>
```

## Retry Configuration

## CLI Usage

You can specify a model when starting the agent:

```bash
# Use specific model for a single task
python main.py --task "Calculate 1+1" --model openai/gpt-4o

# Start interactive mode with specific model
python main.py --model openai/gpt-4o
```

## Validation

```bash
# Sanity check (requires correct API key for your model)
python main.py --task "Calculate 1+1"

# Run tests
python -m pytest test/
```

## Security Notes

- `.aloop/models.yaml` is automatically gitignored to prevent accidental commits of API keys
- Keep your API keys secure and rotate them regularly
- The YAML file permissions should be set to user-readable only (0600) on Unix systems
