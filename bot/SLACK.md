# Slack Bot Setup

This guide walks you through connecting ouro to Slack as an IM bot via Socket Mode.

## Prerequisites

- A [Slack workspace](https://slack.com/) where you can install apps
- `pip install ouro-ai[bot]`

## 1. Create a Slack App

1. Go to [Slack API - Your Apps](https://api.slack.com/apps)
2. Click **Create New App** -> **From scratch**
3. Give it a name (e.g. "Ouro Bot") and select your workspace

## 2. Enable Socket Mode

Go to **Socket Mode** (left sidebar) -> **Enable Socket Mode**

Generate an **App-Level Token** with the `connections:write` scope. This gives you an `xapp-...` token.

## 3. Subscribe to Events

Go to **Event Subscriptions** -> **Enable Events**

Under **Subscribe to bot events**, add:

| Event | Description |
|-------|-------------|
| `message.im` | Receive direct messages |
| `message.channels` | Receive messages in public channels (optional) |

## 4. Set Bot Scopes

Go to **OAuth & Permissions** -> **Scopes** -> **Bot Token Scopes**, add:

| Scope | Description |
|-------|-------------|
| `chat:write` | Send messages |
| `im:history` | Read DM history |
| `channels:history` | Read channel history (if using `message.channels`) |

## 5. Install the App

Go to **Install App** -> **Install to Workspace** -> Authorize

Copy the **Bot User OAuth Token** (`xoxb-...`).

## 6. Run

Add credentials to `~/.ouro/config`:

```
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
```

Then start:

```bash
ouro --bot
```

You should see:

```
Bot server listening on 0.0.0.0:8080
  Active channels: slack
```

## 7. Test

Open a DM with your bot in Slack and send a message. You should receive "Working on it..." followed by the agent's response.

## Running Both Lark and Slack

Add all four keys to `~/.ouro/config` and both channels will be active:

```
LARK_APP_ID=cli_xxx
LARK_APP_SECRET=xxx
SLACK_BOT_TOKEN=xoxb-xxx
SLACK_APP_TOKEN=xapp-xxx
```

```
Bot server listening on 0.0.0.0:8080
  Active channels: lark, slack
```

## Troubleshooting

### Bot doesn't respond

- Check that Socket Mode is enabled in the Slack app settings
- Verify the bot has been invited to the channel (for non-DM channels)
- Check that the `xapp-` token has the `connections:write` scope

### "invalid_auth" errors

- Ensure `SLACK_BOT_TOKEN` starts with `xoxb-`
- Ensure `SLACK_APP_TOKEN` starts with `xapp-`
- Re-install the app to your workspace if tokens have been rotated
