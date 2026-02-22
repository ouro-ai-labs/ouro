# RFC 014: Proactive Mechanisms — Heartbeat, Cron & Agent-Facing Management Tools

- Status: Implemented
- Authors: luohaha
- Date: 2026-02-22

## Summary

Add **proactive background mechanisms** (periodic heartbeat checks + cron-scheduled tasks) to bot mode, and two agent-facing tools (`manage_cron`, `manage_heartbeat`) that let the agent manage these mechanisms on behalf of the user during conversation.

## Problem

Bot mode (RFC 012) is purely reactive — it only responds when the user sends a message. Users want their bot to:

1. **Periodically self-check** — e.g. "every hour, check if any pending tasks need follow-up" — without being prompted.
2. **Schedule recurring tasks** — e.g. "every day at 9am, generate a daily report" — via natural language in chat.
3. **Edit the heartbeat checklist** — the file at `~/.ouro/bot/heartbeat.md` is not easily accessible to non-technical users; they need the bot to manage it for them.

**Example**: A user messages the bot "帮我每天早上9点发一份日报" (schedule a daily report at 9am). Today this is impossible — there is no scheduling primitive and no tool for the agent to call.

## Goals

- Heartbeat: periodic background checks with configurable interval, active-hours gating, and broadcast to active sessions
- Cron: persistent scheduled jobs (cron expressions or fixed intervals) with add/remove/list API
- `manage_cron` tool: agent can add/remove/list cron jobs during conversation
- `manage_heartbeat` tool: agent can add/remove/list heartbeat checklist items during conversation
- Both tools injected automatically in bot mode's `agent_factory`

## Non-goals

- Web UI or dashboard for cron/heartbeat management
- Per-user or per-session heartbeat/cron isolation (all proactive tasks are global for MVP)
- Streaming proactive results to IM (one-shot broadcast only)
- Changes to interactive or `--task` modes

## Proposed Behavior (User-Facing)

### Heartbeat

- Runs every `BOT_HEARTBEAT_INTERVAL` seconds (default: 3600, set to 0 to disable)
- Reads `~/.ouro/bot/heartbeat.md` on each tick
- Skips ticks outside active hours (`BOT_ACTIVE_HOURS_START`/`END`/`TZ`)
- Runs checklist in an isolated one-shot agent (no conversation history)
- If agent responds `HEARTBEAT_OK` → silent; otherwise broadcasts result to all active sessions

### Cron

- Jobs stored in `~/.ouro/bot/cron_jobs.json`, survives restarts
- Supports cron expressions (`0 9 * * *`) and fixed intervals in seconds (`3600`)
- Each tick (every 60s) checks all enabled jobs, executes due ones via isolated agent
- Respects active-hours gating
- Results broadcast to all active sessions

### Slash commands

```
/heartbeat  — Show heartbeat status (enabled/disabled, interval, last/next run)
/cron list  — List all cron jobs
/cron add <schedule> <prompt>  — Add a job
/cron remove <id>  — Remove a job
```

### Agent tools

The agent can call these tools during conversation when the user asks to manage schedules or checklist items:

**`manage_cron`** (operations: `add`, `remove`, `list`):
```json
{"operation": "add", "schedule": "0 9 * * *", "prompt": "生成今日工作日报", "name": "Daily report"}
{"operation": "list"}
{"operation": "remove", "job_id": "abc123def456"}
```

**`manage_heartbeat`** (operations: `add`, `remove`, `list`):
```json
{"operation": "add", "item": "Check if CI pipeline is green"}
{"operation": "list"}
{"operation": "remove", "index": 2}
```

### Config changes (`~/.ouro/config`)

```
# Heartbeat (seconds, 0 = disabled)
BOT_HEARTBEAT_INTERVAL=3600

# Active hours (proactive tasks only run in this window)
BOT_ACTIVE_HOURS_START=8
BOT_ACTIVE_HOURS_END=22
BOT_ACTIVE_HOURS_TZ=Asia/Shanghai
```

## Invariants (Must Not Regress)

- Existing bot message routing and slash commands unchanged
- Session lifecycle (create/cleanup/reset) unchanged
- Channel start/stop lifecycle unchanged
- Existing tool execution pipeline unchanged
- Skills and soul injection in agent_factory unchanged
- `ouro --task` and interactive modes unaffected

## Design Sketch (Minimal)

### Architecture

```
bot/proactive.py
├── IsolatedAgentRunner     — run_isolated() + broadcast()
├── HeartbeatScheduler       — periodic loop, reads heartbeat.md
├── CronScheduler         — tick loop, persists to cron_jobs.json
└── helpers               — load_heartbeat(), is_active_hours()

tools/cron_tool.py        — CronTool(BaseTool), delegates to CronScheduler
tools/heartbeat_tool.py   — HeartbeatTool(BaseTool), reads/writes heartbeat.md directly
```

### IsolatedAgentRunner

Shared execution engine for both heartbeat and cron:

- `run_isolated(prompt)`: creates a one-shot agent via `agent_factory`, runs prompt with a hard timeout (120s), returns result string
- `broadcast(text)`: pushes text to all active IM sessions, skipping busy ones

### HeartbeatTool vs HeartbeatScheduler

`HeartbeatScheduler` reads `heartbeat.md` on each tick to build the agent prompt. `HeartbeatTool` reads/writes the same file to let the agent add/remove items. They share the file path but are otherwise independent — no runtime coupling.

### Tool injection

In `bot/server.py`'s `agent_factory`:

```python
agent.tool_executor.add_tool(CronTool(cron_scheduler))
agent.tool_executor.add_tool(HeartbeatTool())
```

`CronTool` needs the `CronScheduler` instance (to mutate jobs in memory + persist). `HeartbeatTool` only needs the file path (default `~/.ouro/bot/heartbeat.md`).

## Alternatives Considered

- **HeartbeatTool wraps HeartbeatScheduler**: Rejected — `HeartbeatScheduler` is a background loop, not a data store. Direct file I/O is simpler and avoids coupling the tool to the runner lifecycle.
- **In-memory cron storage only**: Rejected — jobs must survive bot restarts. JSON file is simple and sufficient.
- **Single unified `manage_proactive` tool**: Rejected — heartbeat and cron have different parameters and semantics. Separate tools are clearer for the LLM.
- **Database-backed persistence**: Over-engineering for MVP. A JSON file and a markdown file are sufficient for the expected scale (< 100 items).

## Test Plan

- Unit tests:
  - `test/test_bot_proactive.py` — HeartbeatScheduler, CronScheduler, IsolatedAgentRunner, active hours (42 tests)
  - `test/test_cron_tool.py` — CronTool add/remove/list/edge cases (12 tests)
  - `test/test_heartbeat_tool.py` — HeartbeatTool add/remove/list/edge cases (13 tests)
  - `test/test_bot_server.py` — BotServer with proactive components wired in
- Targeted tests: `./scripts/dev.sh test -q`
- Smoke run: `ouro --bot` starts with heartbeat + cron enabled; `/heartbeat` and `/cron list` respond correctly

## Rollout / Migration

- Backward compatibility: fully additive, no breaking changes
- New config keys have sensible defaults (heartbeat=3600s, active hours 8–22)
- `croniter` added as a dependency for cron expression parsing
- No migration needed for existing users; `~/.ouro/bot/` directory created on first use

## Risks & Mitigations

- **Runaway proactive tasks**: Mitigated by 120s hard timeout on isolated agent runs and active-hours gating.
- **Token cost from frequent heartbeats**: Mitigated by configurable interval (default 1 hour) and `HEARTBEAT_OK` short-circuit (no broadcast when nothing to report).
- **File contention (heartbeat.md)**: Low risk — heartbeat reads once per tick (hourly), tool writes are user-initiated and infrequent. No locking needed at this scale.
- **Cron job accumulation**: Low risk — users manage jobs explicitly via tool/slash command. Could add a max-jobs limit later if needed.

## Open Questions

- Should cron jobs support enable/disable toggle (in addition to remove)?
- Should heartbeat checklist items support checked state (`- [x]`) for "done until next cycle"?
- Should proactive results be sent to a specific conversation or all active sessions?
