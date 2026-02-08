# RFC 005: Timer Tool & Notify Tool

**Status**: Partially Rejected (NotifyTool removed)
**Created**: 2026-01-29
**Updated**: 2026-02-03

**Note**: NotifyTool has been removed from the codebase as it required external configuration (Resend API) and had limited use cases. Email notifications can be achieved through shell commands or custom extensions when needed.

## Problem Statement

ouro currently has no way for an agent to schedule delayed or periodic tasks, nor to send notifications to users outside the terminal. This limits the agent to purely synchronous, on-demand interactions.

Two common use cases motivate this RFC:

1. **Scheduled tasks**: An agent should be able to wait for a specified duration or until a cron-scheduled time before executing a task (e.g., "every morning at 9 AM, fetch news and send a summary").
2. **Email notifications**: An agent should be able to send email notifications as part of task execution (e.g., sending a daily digest after gathering information).

## Design Goals

- **Async-first**: Both tools use `asyncio.sleep` / `aiosmtplib` — no blocking I/O.
- **Simple agent integration**: The agent calls TimerTool, which blocks (awaits) until the trigger time, then returns a message. The agent then acts on it. For recurring tasks, the agent simply calls TimerTool again.
- **Minimal configuration**: NotifyTool reads SMTP settings from `.ouro/config`. TimerTool requires no external configuration.

## Proposed Approach

### TimerTool

The agent calls TimerTool with a mode, value, and task description. The tool awaits internally until the specified time, then returns the task description back to the agent.

**Modes:**
- `delay`: Sleep for N seconds, trigger once.
- `interval`: Sleep for N seconds (semantically identical to delay for a single invocation; the agent decides whether to loop).
- `cron`: Parse a cron expression, compute seconds until the next trigger, then sleep.

**Parameters:**
- `mode` (string, required): `"delay"` | `"interval"` | `"cron"`
- `value` (string, required): Seconds (for delay/interval) or a cron expression (for cron mode)
- `task` (string, required): Task description returned when the timer fires

**Return format:** `"Timer triggered. Task to execute: {task}"`

Cron parsing uses the `croniter` library to compute the next fire time.

### NotifyTool

Sends an email via the [Resend](https://resend.com) HTTP API. Uses `httpx` (already a project dependency), no extra packages needed.

**Parameters:**
- `recipient` (string, required): Recipient email address
- `subject` (string, required): Email subject
- `body` (string, required): Email body (plain text)

**Configuration** (`.ouro/config`):
- `RESEND_API_KEY`: Resend API key
- `NOTIFY_EMAIL_FROM`: Sender address (e.g. `ouro <onboarding@resend.dev>`)

## Alternatives Considered

- **Background scheduling with callback**: More complex, requires managing background tasks and callback mechanisms. The synchronous "sleep then return" approach is simpler and fits the ReAct loop naturally.
- **OS-level cron**: Would require external setup and wouldn't integrate with the agent loop.

## Open Questions

- Should there be a maximum sleep duration to prevent indefinite hangs? Currently left to the tool timeout configuration.
- Should NotifyTool support HTML email bodies? Starting with plain text only for simplicity.
