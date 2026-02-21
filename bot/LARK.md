# Lark (Feishu) Bot Setup

This guide walks you through connecting ouro to Lark as an IM bot.

## Prerequisites

- A [Lark Open Platform](https://open.feishu.cn/app) account (enterprise admin or developer)
- `pip install ouro-ai[bot]`

## 1. Create a Lark App

1. Go to [Lark Open Platform](https://open.feishu.cn/app)
2. Click **Create Custom App**
3. Fill in app name (e.g. "Ouro Bot") and description

## 2. Get Credentials

In your app's **Credentials & Basic Info** page, note down:

- **App ID** (`cli_xxx`)
- **App Secret**

## 3. Enable Bot Capability

Go to **Features** -> **Bot** -> Enable

## 4. Enable Long Connection (WebSocket)

Go to **Events & Callbacks** -> **Callback Configuration** -> Switch to **Long Connection (WebSocket)**

This is the key step -- it means no public URL is needed.

## 5. Subscribe to Events

Go to **Events & Callbacks** -> **Event Configuration** -> Add event:

| Event | Event Name |
|-------|------------|
| Receive message | `im.message.receive_v1` |

**Note**: The app must be running (`ouro --bot`) when you save event subscriptions, because Lark verifies the WebSocket connection is active.

## 6. Add Permissions

Go to **Permissions & Scopes** -> search and enable:

- `im:message` -- Read messages in chats
- `im:message:send_as_bot` -- Send messages as the bot

## 7. Publish the App

Go to **Version Management & Release** -> **Create Version** -> Submit for review.

For enterprise custom apps, approval is usually automatic.

## 8. Run

Add credentials to `~/.ouro/config`:

```
LARK_APP_ID=cli_xxx
LARK_APP_SECRET=your_app_secret
```

Then start:

```bash
ouro --bot
```

You should see:

```
Bot server listening on 0.0.0.0:8080
  Active channels: lark
```

## 9. Test

Find your bot in Lark and send a message. You should receive "Working on it..." followed by the agent's response.

## Troubleshooting

### "connecting through a SOCKS proxy requires python-socks"

Your environment has a SOCKS proxy configured. Install the adapter:

```bash
pip install "python-socks[asyncio]"
```

### "This event loop is already running"

This should not happen with the current implementation (we create a dedicated event loop for the SDK thread). If you see this, please file an issue.

### Event subscription fails with "app has not established long connection"

Make sure `ouro --bot` is running **before** you save the event subscription in the Lark console. Lark needs to verify the WebSocket connection is active.
