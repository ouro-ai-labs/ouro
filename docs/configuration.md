# Configuration Guide

This repo uses a **single configuration surface** via `.aloop/config` and `config.py`.

## Configuration File

On first run, `.aloop/config` is created automatically with sensible defaults. Edit it to configure your LLM provider:

```bash
# Open the config file
$EDITOR .aloop/config
```

## LLM Configuration (Recommended: LiteLLM)

### Required

```bash
# Format: provider/model_name
LITELLM_MODEL=anthropic/claude-3-5-sonnet-20241022

# Set the key for your chosen provider
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=
GEMINI_API_KEY=
```

LiteLLM auto-detects which key is needed based on the `LITELLM_MODEL` prefix.

### Model Examples

```bash
# Anthropic
LITELLM_MODEL=anthropic/claude-3-5-sonnet-20241022

# OpenAI
LITELLM_MODEL=openai/gpt-4o

# Gemini
LITELLM_MODEL=gemini/gemini-1.5-pro
```

For the full list of providers/models, see: https://docs.litellm.ai/docs/providers

### Base URL (Optional)

Use this for proxies or custom endpoints:

```bash
LITELLM_API_BASE=
```

### LiteLLM Behavior (Optional)

```bash
LITELLM_DROP_PARAMS=true
LITELLM_TIMEOUT=600
```

## Tool Configuration

```bash
TOOL_TIMEOUT=600
```

### Legacy (Compatibility)

This repo does not support legacy `LLM_PROVIDER` / `MODEL` configuration. Use `LITELLM_MODEL`.

## Agent Configuration

```bash
MAX_ITERATIONS=100
```

## Memory Configuration

```bash
MEMORY_ENABLED=true
MEMORY_COMPRESSION_THRESHOLD=25000
MEMORY_SHORT_TERM_SIZE=100
MEMORY_COMPRESSION_RATIO=0.3
```

## Retry Configuration

```bash
RETRY_MAX_ATTEMPTS=3
RETRY_INITIAL_DELAY=1.0
RETRY_MAX_DELAY=60.0
```

## Validation

```bash
# Sanity check (requires correct API key for your model/provider)
python main.py --task "Calculate 1+1"

# Run tests
python -m pytest test/
```

Integration tests that call a live LLM are skipped by default:

```bash
RUN_INTEGRATION_TESTS=1 python -m pytest -m integration
```

## Security Best Practices

1. Never commit `.aloop/config` or API keys.
2. Treat publishing as a manual step (see `docs/packaging.md`).
3. Keep `MAX_ITERATIONS` low when experimenting to avoid runaway cost.
