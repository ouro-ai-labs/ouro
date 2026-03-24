# WeChat Bot Setup

This guide walks you through connecting ouro to WeChat as an IM bot via the [weixin-bot-sdk](https://github.com/epiral/weixin-bot).

## Prerequisites

- A personal WeChat account (used for the bot)
- `pip install ouro-ai[bot]`

## 1. Enable WeChat Channel

Add the following to `~/.ouro/config`:

```
WECHAT_ENABLED=true
```

## 2. Start the Bot

```bash
ouro --bot
```

On first launch, a **QR code** will be displayed in the terminal. Scan it with the WeChat app on your phone to authenticate. Credentials are cached at `~/.weixin-bot/credentials.json` so you won't need to scan again unless the session expires.

## 3. Send Messages

Once authenticated, anyone who sends a message to the bot's WeChat account will receive AI-powered replies from ouro.

## How It Works

- **Authentication**: QR code login via the iLink Bot protocol
- **Message polling**: Long-polling loop runs in a background thread
- **Conversations**: Each WeChat user maps to a separate ouro session (1:1)
- **Slash commands**: `/new`, `/status`, `/compact`, `/help` etc. work the same as other channels

## Limitations

- **Text only**: Currently only text messages are processed. Images, voice, video, and file attachments are ignored.
- **No reactions**: WeChat does not support emoji reactions on messages, so the 👀/✅ processing indicators are not shown.
- **No file sending**: The SDK does not support sending files/images back to users.
- **Session expiry**: If the session expires (error code `-14`), the bot will need to re-authenticate. Restart the bot to trigger a new QR code.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| QR code not showing | Make sure your terminal supports the QR display. Try a wider terminal window. |
| Session expired | Restart the bot (`ouro --bot`) and scan the QR code again. |
| `weixin-bot-sdk not installed` | Run `pip install weixin-bot-sdk` or `pip install ouro-ai[bot]`. |
| Messages not received | Check that the WeChat account is logged in and the bot thread is running (check logs). |
