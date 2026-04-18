# Bot Mode Guide

Run ouro as a persistent IM bot — message it from Lark or Slack, get agent responses. No public URL needed; the bot uses outbound long connections (WebSocket / Socket Mode).

Bot data is isolated under `~/.ouro/bot/` (sessions, memory, skills) so it never conflicts with CLI mode.

## Installation

```bash
pip install ouro-ai[bot]
```

## Configure Models

The bot uses the same `~/.ouro/models.yaml` as CLI mode. On first run it is created with a template — add your provider and API key:

```yaml
models:
  openai/gpt-4o:
    api_key: sk-...

  anthropic/claude-sonnet-4:
    api_key: sk-ant-...

  ollama/llama2:
    api_base: http://localhost:11434

default: openai/gpt-4o
current: openai/gpt-4o
```

See [LiteLLM Providers](https://docs.litellm.ai/docs/providers) for the full list. For advanced model settings, see [Configuration](configuration.md).

> **Note:** Bot mode does not support OAuth (`chatgpt/*`) models yet. Use API-key-based providers.

## Quick Start

Add IM platform credentials to `~/.ouro/config`:

```
# Lark
LARK_APP_ID=cli_xxx
LARK_APP_SECRET=xxx

# Slack
SLACK_BOT_TOKEN=xoxb-xxx
SLACK_APP_TOKEN=xapp-xxx
```

```bash
ouro --bot
```

## Session Persistence

Bot conversations are automatically saved to disk and resumed across restarts. Each IM conversation gets its own session, mapped via `~/.ouro/bot/sessions/conversation_map.yaml`.

Sessions untouched for 30 days are automatically cleaned up.

## Bot Commands

Send these as a message to the bot:

| Command | Description |
|---------|-------------|
| `/new` or `/reset` | Start a fresh session |
| `/sessions list` | List all saved sessions |
| `/sessions resume <id>` | Switch to a previous session |
| `/compact` | Compress conversation memory to save tokens |
| `/status` | Show session statistics (age, messages, tokens, compressions) |
| `/cron list` | List all scheduled cron jobs |
| `/cron add [--session main\|isolated\|current] [--deliver auto\|broadcast\|none\|announce:<ch>:<conv>] <schedule> <prompt>` | Create a new cron job |
| `/cron remove <id>` | Delete a cron job |
| `/help` | List all available commands |

## Proactive Mechanisms

The bot can act on its own between conversations via scheduled cron jobs.

Each job picks a **session mode** (where the prompt runs) and a **delivery** target (where the reply goes):

| Session mode | Runs in | Default use |
|---|---|---|
| `main` (default) | The most recently active IM session's agent (reuses history) | Personal reminders, periodic checks |
| `isolated` | A throwaway one-shot agent (no conversation history) | Fresh reports, broadcast pings |
| `current` | A specific session bound at creation time (via `/cron add --session current`) | "Remind me in *this* chat every morning" |

Delivery defaults to `auto` (reply goes to the session the job ran in, or broadcasts for `isolated`). Override with `--deliver broadcast`, `--deliver none`, or `--deliver announce:<channel>:<conversation_id>`.

See [Configuration](configuration.md) for `BOT_PROACTIVE_TIMEOUT`, `BOT_ACTIVE_HOURS_*`, and other settings.

## Personality

`~/.ouro/bot/soul.md` defines the bot's identity and tone. It is injected into the agent's system prompt for all bot sessions. A default template is created automatically on first launch — edit it to customize your bot's personality.

## Platform Setup

- [Lark (Feishu) Setup](../bot/LARK.md)
- [Slack Setup](../bot/SLACK.md)
