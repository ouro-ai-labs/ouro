# Configuration

## Model Configuration

Models are configured in `~/.ouro/models.yaml` (auto-created on first run).

```yaml
models:
  anthropic/claude-3-5-sonnet-20241022:
    api_key: sk-ant-...
    timeout: 600
    drop_params: true

  openai/gpt-4o:
    api_key: sk-...

  chatgpt/gpt-5.3-codex:
    timeout: 600

  ollama/llama2:
    api_base: http://localhost:11434

default: anthropic/claude-3-5-sonnet-20241022
```

The model ID (key under `models`) uses the LiteLLM `provider/model` format. See [LiteLLM Providers](https://docs.litellm.ai/docs/providers) for supported providers.

### Model Fields

| Field | Required | Description |
|-------|----------|-------------|
| `api_key` | Yes* | Provider API key |
| `api_base` | No | Custom base URL (proxies, Azure, local models) |
| `timeout` | No | Request timeout in seconds |
| `drop_params` | No | Drop unsupported params silently |

*Not required for local models (e.g., Ollama) or `chatgpt/*` subscription models.

### Model Management

**CLI**: `ouro --model openai/gpt-4o` or `python main.py --model openai/gpt-4o`

**Interactive**:
- `/model` -- pick from configured models (arrow keys + Enter)
- `/model edit` -- open `~/.ouro/models.yaml` in your editor (auto-reload on save)

### ChatGPT / Codex Subscription Login

For `chatgpt/*` models, login with OAuth before first use:

- CLI: `ouro --login` (then pick provider)
- Interactive: `/login` (then pick provider)
- Logout: `ouro --logout` or `/logout`
- After login, use `/model` to pick one of the added `chatgpt/*` models.
- The added set comes from ouro's bundled OAuth catalog (synced from pi-ai `openai-codex` model list, including GPT-5.3 Codex variants).

The device-login page is opened in browser on a best-effort basis when fresh authorization is likely needed. If your existing token/refresh state is still valid, login usually completes without a new browser step. If your environment blocks browser launch, open `https://auth.openai.com/codex/device` manually and enter the code shown in terminal.

Credentials are stored under `~/.ouro/auth/chatgpt/`.

Maintainer note: refresh the bundled OAuth model catalog with `python scripts/update_oauth_model_catalog.py`.

## Runtime Settings

Settings live in `~/.ouro/config` (KEY=VALUE format, auto-created with defaults).

### Agent

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_ITERATIONS` | `1000` | Maximum agent loop iterations |
| `TOOL_TIMEOUT` | `600` | Tool execution timeout in seconds |
| `RALPH_LOOP_MAX_ITERATIONS` | `3` | Max Ralph verification attempts |

### Memory

| Setting | Default | Description |
|---------|---------|-------------|
| `MEMORY_ENABLED` | `true` | Enable memory management |
| `MEMORY_COMPRESSION_THRESHOLD` | `60000` | Token count that triggers compression |
| `MEMORY_SHORT_TERM_SIZE` | `100` | Max recent messages kept at full fidelity |
| `MEMORY_SHORT_TERM_MIN_SIZE` | `6` | Minimum messages to always preserve |
| `MEMORY_COMPRESSION_RATIO` | `0.3` | Target compression ratio (0.3 = 30% of original) |

### Retry

| Setting | Default | Description |
|---------|---------|-------------|
| `RETRY_MAX_ATTEMPTS` | `3` | Retry attempts on rate-limit (429) errors |
| `RETRY_INITIAL_DELAY` | `1.0` | Initial retry delay in seconds |
| `RETRY_MAX_DELAY` | `60.0` | Maximum retry delay in seconds |

Retry uses exponential backoff with jitter: `delay = min(initial * 2^attempt, max_delay) * uniform(0.75, 1.25)`.

### TUI

| Setting | Default | Description |
|---------|---------|-------------|
| `TUI_THEME` | `dark` | Theme (`dark` or `light`) |
| `TUI_SHOW_THINKING` | `true` | Show agent thinking display |
| `TUI_THINKING_MAX_PREVIEW` | `300` | Max characters in thinking preview |
| `TUI_STATUS_BAR` | `true` | Show status bar (tokens, cost, model) |
| `TUI_COMPACT_MODE` | `false` | Compact output mode |

### Notifications

| Setting | Default | Description |
|---------|---------|-------------|
| `RESEND_API_KEY` | `""` | [Resend](https://resend.com) API key for email notifications |
| `NOTIFY_EMAIL_FROM` | `""` | Email sender address |

### Logging

| Setting | Default | Description |
|---------|---------|-------------|
| `LOG_LEVEL` | `DEBUG` | Logging level |

## Custom Endpoints

Use `api_base` to route requests through proxies, Azure, or local servers:

```yaml
models:
  # Corporate proxy
  openai/gpt-4o:
    api_key: sk-...
    api_base: http://proxy.company.com

  # Azure OpenAI
  azure/gpt-4:
    api_key: your_azure_key
    api_base: https://your-resource.openai.azure.com

  # Local model
  ollama/llama2:
    api_base: http://localhost:11434
```

## Security

- `~/.ouro/models.yaml` contains API keys. Never commit them to version control.
- ChatGPT OAuth credentials are stored in `~/.ouro/auth/chatgpt/`.
- Set file permissions to `0600` on Unix: `chmod 600 ~/.ouro/models.yaml`
- Rotate API keys regularly.
