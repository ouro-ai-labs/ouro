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

Login uses a browser-based OAuth (PKCE) flow with a localhost callback server, which works in workspaces that disable the OAuth device-code grant. If browser launch is blocked, ouro prints a URL you can open manually. For remote machines, you may need SSH port-forwarding to reach the localhost callback server.

Credentials are stored under `~/.ouro/auth/chatgpt/` (LiteLLM-compatible `auth.json`).

Advanced environment overrides (rarely needed; defaults work for most users):

| Env var | Default | Notes |
|--------|---------|------|
| `CHATGPT_TOKEN_DIR` | `~/.ouro/auth/chatgpt/` | Where `auth.json` is stored (also used by LiteLLM). |
| `CHATGPT_AUTH_FILE` | `auth.json` | Override the auth filename under `CHATGPT_TOKEN_DIR`. |
| `OURO_NO_BROWSER` | unset | Set to `1` to disable auto-opening the browser (URL is still printed). |
| `OURO_CHATGPT_OAUTH_TIMEOUT_SECONDS` | `600` | How long to wait for the localhost callback before prompting for manual paste. |
| `OURO_CHATGPT_OAUTH_CALLBACK_HOST` | `127.0.0.1` | Address to bind the local callback server to. The browser redirect is always `http://localhost:<port>/auth/callback`. |
| `OURO_CHATGPT_OAUTH_CALLBACK_PORT` | `1455` | Port for the local callback server. Set to `0` to auto-pick an available port if 1455 is in use. |
| `OURO_CHATGPT_OAUTH_ALLOW_NON_LOOPBACK` | unset | Set to `1` to allow binding callback server to a non-loopback address (not recommended). |
| `OURO_CHATGPT_OAUTH_AUTHORIZE_URL` | `https://auth.openai.com/oauth/authorize` | Override authorization endpoint (enterprise proxies/SSO gateways). |
| `OURO_CHATGPT_OAUTH_TOKEN_URL` | `https://auth.openai.com/oauth/token` | Override token/refresh endpoint. |
| `OURO_CHATGPT_OAUTH_HTTP_TIMEOUT_SECONDS` | `30` | HTTP timeout for token/refresh requests. |
| `OURO_CHATGPT_USER_AGENT` | `Mozilla/5.0 (compatible; ouro/1.0)` | Override User-Agent header for token/refresh requests. |
| `OURO_CHATGPT_OAUTH_ORIGINATOR` | `codex_cli_rs` | OAuth `originator` query param (rarely needed). |

Advanced environment overrides (rarely needed):
- `OURO_CHATGPT_OAUTH_AUTHORIZE_URL`: override the authorization endpoint.
- `OURO_CHATGPT_OAUTH_TOKEN_URL`: override the token/refresh endpoint.
- `OURO_CHATGPT_OAUTH_HTTP_TIMEOUT_SECONDS`: HTTP timeout for token/refresh requests.
- `OURO_CHATGPT_USER_AGENT`: override User-Agent header for token/refresh requests.
- `OURO_CHATGPT_OAUTH_ALLOW_NON_LOOPBACK`: allow binding the localhost callback server to a non-loopback address (not recommended).

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
