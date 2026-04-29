# RFC 015: Heartbeat Refactor — System Prompt Injection + Main Session

- Status: Implemented
- Authors: ouro-dev
- Date: 2026-03-01

## Summary

Migrate the heartbeat mechanism from a dedicated `HeartbeatTool` + isolated session to a system prompt injection + main session trigger model. The agent manages `heartbeat.md` through existing file tools (`read_file` / `write_file` / `smart_edit`) instead of a purpose-built tool, and heartbeat ticks execute in the most recently active conversation session.

## Problem

The previous design used two separate components that overlapped in responsibility:

1. `HeartbeatTool` — a structured tool (`manage_heartbeat`) with `add/remove/list` operations on `- [ ] ` checklist items in `heartbeat.md`.
2. `HeartbeatScheduler` — ran periodic checks in an isolated one-shot session, reading the same file.

Issues:
- **Redundant tool**: the agent already has `read_file`, `write_file`, and `smart_edit` which can manage any markdown file. A dedicated structured tool adds API surface without meaningful capability.
- **Isolated session loses context**: heartbeat ticks ran in throwaway sessions with no conversation history, meaning the agent couldn't reference prior context when evaluating heartbeat items.
- **Rigid format**: the `- [ ] ` checklist format was enforced by `HeartbeatTool`, preventing free-form markdown (e.g., prose instructions, nested sections, conditional logic).
- **Broadcast noise**: results were broadcast to *all* active sessions rather than the conversation where the user is active.

## Goals

- Let the agent use existing file tools to manage `heartbeat.md` in free-form markdown.
- Inject heartbeat file content into the system prompt so the agent always sees it.
- Run heartbeat ticks in the most recently active session to preserve conversation context.
- Send heartbeat results only to the relevant session (not broadcast).

## Non-goals

- Changing how cron jobs work (they still use `IsolatedAgentRunner` + broadcast).
- Supporting multiple heartbeat files or per-session heartbeat configs.
- Changing the heartbeat file path (`~/.ouro/bot/heartbeat.md`).

## Proposed Behavior (User-Facing)

- **Heartbeat file format**: free-form markdown. Users write whatever instructions they want.
- **Agent interaction**: users ask the agent to edit `~/.ouro/bot/heartbeat.md` using natural language; the agent uses `read_file`/`write_file`/`smart_edit`.
- **System prompt**: heartbeat content is injected as a `<heartbeat>` XML block in the system prompt, visible to the agent on every turn.
- **Heartbeat tick**: the scheduler triggers `agent.run()` in the last-active session with a prompt asking the agent to re-read the file and act on any items.
- **HEARTBEAT_OK**: if the agent responds with `HEARTBEAT_OK`, the result is silently dropped. Otherwise, the response is sent to the active session.

## Invariants (Must Not Regress)

- Heartbeat scheduling (interval, enable/disable) still works as before.
- `/heartbeat` slash command still shows status.
- Cron jobs are unaffected (still use `IsolatedAgentRunner`).
- `load_heartbeat()` still creates a default file if missing.
- Agent system prompt order: base → context → LTM → skills → heartbeat → soul.

## Design Sketch (Minimal)

### Components changed

| Component | Change |
|-----------|--------|
| `agent/agent.py` | New `_heartbeat_section` + `set_heartbeat_section()` + `<heartbeat>` injection in system prompt |
| `bot/proactive.py` | `_has_checklist_items()` → `_has_meaningful_content()`, `HeartbeatScheduler` takes `router` + `channels` instead of `IsolatedAgentRunner`, `_tick()` runs in last-active session |
| `bot/server.py` | `agent_factory()` loads heartbeat content and calls `set_heartbeat_section()` instead of registering `HeartbeatTool` |
| `bot/session_router.py` | New `get_last_active_session()` |
| `tools/heartbeat_tool.py` | Deleted |

### Heartbeat tick flow

1. `load_heartbeat()` reads `heartbeat.md`
2. `_has_meaningful_content()` checks for non-header, non-blank lines
3. `router.get_last_active_session()` finds the most recently active session
4. Acquire the session lock (wait if busy — heartbeat intervals are long enough)
5. `agent.run(heartbeat_prompt)` within the lock
6. If response contains `HEARTBEAT_OK` → silent. Otherwise → send to the channel.

## Alternatives Considered

- **Keep HeartbeatTool alongside system prompt injection**: rejected — two ways to manage the same file creates confusion and the tool adds no capability over existing file tools.
- **Keep isolated sessions but remove the tool**: would lose conversation context which is one of the main motivations for the change.
- **Broadcast heartbeat results to all sessions**: the old behavior; changed to last-active-only since heartbeat is a conversation-level concern.

## Test Plan

- Unit tests: `test/test_bot_proactive.py` — `TestHasMeaningfulContent`, `TestHeartbeatScheduler` (8 tests covering OK/skip/send/lock/error cases)
- Targeted tests: `./scripts/dev.sh test -q test/test_bot_proactive.py`
- Full check: `./scripts/dev.sh check`

## Rollout / Migration

- **Backward compatibility**: existing `heartbeat.md` files with `- [ ] ` checklist format will continue to work — `_has_meaningful_content()` considers them valid content. The agent will read and understand them naturally.
- **Migration steps**: none required. Users who used `manage_heartbeat` tool will now use natural language to edit the file.

## Risks & Mitigations

- **Lock contention**: heartbeat tick waits for the session lock. Mitigated by long heartbeat intervals (default 30 min) and agent timeout.
- **Conversation history growth**: each heartbeat adds one user+assistant turn. Mitigated by the existing memory compression mechanism.
- **System prompt size**: heartbeat content is included in every system prompt. Mitigated by the fact that heartbeat files are typically small (a few lines).

## Open Questions

None — design is implemented and tested.
