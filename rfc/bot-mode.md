# RFC 012: Bot Mode (IM-based Personal Assistant)

- Status: Proposed
- Authors: luohaha
- Date: 2026-02-21

## Summary

Add a persistent **bot mode** (`ouro --bot`) that connects to IM platforms via **long-lived outbound connections** (Lark WebSocket, Slack Socket Mode). No public URL or webhook endpoint needed — the bot initiates all connections, making it practical for local Mac development and private deployments.

## Problem

ouro is currently CLI-only: interactive TUI or single-shot `--task`. Users who want to interact with ouro from their phone, or have it running as a persistent service they can message anytime, have no supported path. Running `ouro --task` in a loop is brittle and loses conversation context.

**Example**: A user wants to ask ouro questions throughout the day from their Lark or Slack chat — researching topics, running code tasks, getting summaries — without needing a terminal open or a public URL.

## Goals

- `ouro --bot` starts a persistent process that connects to IM platforms
- **Lark** channel via `lark-oapi` WebSocket SDK (MVP)
- **Slack** channel via `slack-sdk` Socket Mode (MVP)
- No public URL, ngrok, or webhook configuration required
- Per-conversation session routing (each IM chat gets its own agent with memory)
- Immediate acknowledgment ("Working on it...") + final answer delivery
- Reuse existing `create_agent()` + `agent.run()` — no changes to agent internals
- Clean channel abstraction for adding more platforms later

## Non-goals

- Streaming intermediate tool calls to the IM (future enhancement)
- Multi-user auth / access control (assume trusted private bot for MVP)
- Web UI or dashboard
- Changing the existing interactive or `--task` modes

## Proposed Behavior (User-Facing)

### CLI changes

```
ouro --bot                  # Start bot server (default: 0.0.0.0:8080)
ouro --bot --model gpt-4o   # Start with specific model
```

### Config changes (`~/.ouro/config`)

```
# Bot mode
BOT_HOST=0.0.0.0
BOT_PORT=8080
```

### Environment variables (for secrets)

```
# Lark (WebSocket long connection)
OURO_LARK_APP_ID=cli_xxx
OURO_LARK_APP_SECRET=xxx

# Slack (Socket Mode)
OURO_SLACK_BOT_TOKEN=xoxb-xxx      # Bot User OAuth Token
OURO_SLACK_APP_TOKEN=xapp-xxx      # App-Level Token (connections:write)
```

### Output / logging

- Server startup logs active channels to stderr
- Each message processing logs conversation ID + timing
- Agent output suppressed (quiet mode) — only sent to IM channel

### Message flow (Lark)

1. `ouro --bot` starts -> `lark.ws.Client` opens WebSocket to Lark servers
2. User sends message in Lark chat
3. Lark pushes event over WebSocket -> SDK dispatches to handler
4. Handler bridges to asyncio event loop -> callback processes message
5. Send "Working on it..." -> run agent -> send result via Lark API

### Message flow (Slack)

1. `ouro --bot` starts -> `AsyncSocketModeClient` opens WebSocket to Slack
2. User sends message in Slack
3. Slack pushes event over Socket Mode -> client receives `SocketModeRequest`
4. Ack immediately -> callback processes message
5. Send "Working on it..." -> run agent -> send result via `chat.postMessage`

## Invariants (Must Not Regress)

- `ouro --task "..."` continues to work identically
- `ouro` (interactive mode) continues to work identically
- `--bot` is fully opt-in; no new dependencies required for non-bot users (`lark-oapi` and `slack-sdk` are optional)
- Config file format unchanged; new keys are additive
- No changes to agent internals (`agent.run()`, memory, tools)

## Design Sketch (Minimal)

### Package structure

```
bot/
    __init__.py
    server.py              # Channel lifecycle + health endpoint
    session_router.py      # conversation -> agent mapping
    channel/
        __init__.py
        base.py            # Channel protocol + message dataclasses
        lark.py            # Lark WebSocket (lark-oapi SDK)
        slack.py           # Slack Socket Mode (slack-sdk)
```

### Channel protocol

```python
class Channel(Protocol):
    name: str
    async def start(self, message_callback: Callable[[IncomingMessage], Awaitable[None]]) -> None: ...
    async def stop(self) -> None: ...
    async def send_message(self, message: OutgoingMessage) -> None: ...
```

Each channel owns its own connection lifecycle. `start()` begins receiving messages and invokes the callback for each one. `stop()` tears down the connection cleanly.

### Session router

- `dict[str, LoopAgent]` keyed by `"{channel}:{conversation_id}"`
- Per-conversation `asyncio.Lock` for serialization (agent memory is not concurrent-safe)
- Idle cleanup after configurable timeout

### Server flow

- `start()`: launch each channel via `channel.start(callback)`, start health server
- Callback: lock -> ack -> `agent.run()` -> send result
- `GET /health`: returns `{"status": "ok"}`
- Shutdown: `channel.stop()` for all channels

### Channel details

**Lark WebSocket** (`lark-oapi`):
- `lark.ws.Client.start()` is blocking -> run in daemon thread
- Handler runs in SDK thread -> `asyncio.run_coroutine_threadsafe()` to bridge to event loop
- `lark.Client` for sending messages (sync SDK -> `asyncio.to_thread()`)
- SDK handles token refresh, reconnection, and deduplication automatically

**Slack Socket Mode** (`slack-sdk`):
- `AsyncSocketModeClient` with aiohttp backend -- natively async
- Ack each `SocketModeRequest` immediately via `SocketModeResponse`
- Filter: only `events_api` / `message` events, skip bot messages and edits
- Dedup by `client_msg_id` with bounded dict
- Send via `AsyncWebClient.chat_postMessage()`

## Alternatives Considered

- **Webhook-based**: Receive messages via HTTP POST to a public endpoint. Rejected: requires public URL or ngrok, impractical for local Mac development. Long connections are simpler and more reliable.
- **Polling-based**: Poll an API for new messages. Rejected: higher latency, more complex state management, not how IM platforms work.
- **Modify agent.run() for streaming**: Rejected for MVP. The current `run() -> str` interface is clean and sufficient. Streaming can be added later.

## Test Plan

- Unit tests:
  - `test/test_bot_session_router.py`: session creation, lock serialization, idle cleanup (unchanged)
  - `test/test_lark_channel.py`: WS handler, send_message, thread->asyncio bridge
  - `test/test_slack_channel.py`: event parsing, bot filtering, dedup, ack, send
  - `test/test_bot_server.py`: FakeChannel lifecycle, callback wiring, health endpoint
- Targeted tests to run locally: `./scripts/dev.sh test -q`
- Smoke run: `ouro --bot` starts, `curl localhost:8080/health` returns OK

## Rollout / Migration

- Backward compatibility: fully additive, no breaking changes
- `lark-oapi` and `slack-sdk` are optional dependencies: `pip install ouro-ai[bot]`
- No migration needed for existing users

## Risks & Mitigations

- **Long-running agent blocks conversation**: Mitigated by per-conversation lock + immediate ack.
- **Memory leak from abandoned sessions**: Mitigated by idle session cleanup with configurable timeout.
- **Lark WebSocket disconnection**: Mitigated by lark-oapi SDK auto-reconnection.
- **Slack Socket Mode disconnection**: Mitigated by slack-sdk auto-reconnection.
- **Thread safety (Lark)**: SDK callback runs in SDK thread; bridged to asyncio event loop via `run_coroutine_threadsafe()`.
- **Secrets in config**: Mitigated by using environment variables (`OURO_LARK_*`, `OURO_SLACK_*`) as primary source.

## Open Questions

- Should bot mode support `--resume` to restore previous bot sessions on restart?
- Should there be a max concurrent conversations limit?
- Should the bot respond differently to group chats vs. direct messages?
