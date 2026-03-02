# RFC 012: Bot Message Queue with Intelligent Coalescing

- Status: Proposed
- Authors: ouro team
- Date: 2026-03-01

## Summary

When users send rapid-fire messages to the bot via IM (a common pattern — splitting
thoughts across messages, adding images after text), each message triggers a separate
`agent.run()` call. This RFC introduces a per-conversation message queue with debounce
and intelligent coalescing so that rapid-fire messages are batched into a single agent
call, making the bot feel more like chatting with a human who reads all messages before
responding.

## Problem

Current behavior: each IM message is processed independently via a per-conversation
lock. When a user sends three messages in quick succession:

1. Message 1 starts processing (acquires lock).
2. Messages 2 and 3 block on the lock.
3. Each gets a separate `agent.run()` call — tripling latency and token cost.
4. The agent never sees all three messages together, missing context.

Example: "Can you check the sales data?" → "For Q4 2025" → [attaches spreadsheet].
Today this produces three separate agent responses instead of one coherent one.

## Goals

- Batch rapid-fire messages into a single `agent.run()` call.
- Configurable debounce window (`BOT_DEBOUNCE_SECONDS`, default 1.5s).
- Safety cap on batch size (`BOT_MAX_BATCH_SIZE`, default 20).
- Every message gets instant 👀 reaction; all batch messages get ✅ after completion.
- Replace per-conversation locks with queue-based serialization.

## Non-goals

- Cross-conversation batching (each conversation is independent).
- Deduplication of message content.
- Persistent queue (in-memory only; messages in flight are lost on crash).

## Proposed Behavior (User-Facing)

- CLI / UX changes: none (bot mode only).
- Config changes: two new optional keys in `~/.ouro/config`:
  - `BOT_DEBOUNCE_SECONDS=1.5` — sliding window before processing.
  - `BOT_MAX_BATCH_SIZE=20` — max messages per batch.
- Output / logging changes: log lines show batch size and coalescing info.

Observable behavior:
1. User sends message → instant 👀 reaction.
2. User sends more messages within 1.5s → each gets 👀 immediately.
3. After 1.5s of silence → all messages coalesced, single `agent.run()`.
4. Response sent → all messages in batch get ✅.

## Invariants (Must Not Regress)

- Slash commands remain instant (bypass queue).
- Per-conversation isolation maintained.
- Every received message gets 👀 immediately.
- Every processed message gets ✅ after completion.
- Error messages still sent to user on agent failure.
- Session persistence (`update_session_mapping`) still called.
- Temp file cleanup on all code paths.

## Design Sketch (Minimal)

### New module: `bot/message_queue.py`

Three components:

1. **`CoalescedBatch`** dataclass — holds merged text, images, files, and source
   message references for reaction management.

2. **`coalesce_messages()`** — pure function that merges a list of `IncomingMessage`:
   - Single user: join texts with `\n\n`.
   - Multi-user: prefix each with `[user_id]`.
   - Collects all images/files into flat lists.

3. **`ConversationQueue`** — per-conversation async queue with:
   - Sliding-window debounce collection.
   - Auto-starting consumer task on first enqueue.
   - Auto-stopping consumer after idle timeout.

4. **`MessageQueueManager`** — routes messages to per-conversation queues.

### Lock removal

The per-conversation `asyncio.Lock` in `SessionRouter._locks` is removed. The queue
consumer is the sole entity calling `agent.run()` for a given conversation, providing
natural serialization.

## Alternatives Considered

- **Option A: Keep locks, add debounce in callback.** Simpler, but the lock still
  serializes individual messages — no true batching benefit.
- **Option B: Token-bucket rate limiting.** Reduces load but doesn't coalesce context.

## Test Plan

- Unit tests: `test/test_bot_message_queue.py` — coalescing logic, debounce timing,
  queue lifecycle.
- Targeted tests: `./scripts/dev.sh test -q -k test_bot_message_queue`
- Existing tests: `./scripts/dev.sh test -q -k test_bot_server`
- Smoke run: manual test with Slack/Lark (send 3 rapid messages, verify single response).

## Rollout / Migration

- Backward compatibility: fully backward-compatible; default debounce of 1.5s is
  unnoticeable for normal single-message patterns.
- Migration steps: none required.

## Risks & Mitigations

- **Added latency for single messages**: 1.5s debounce adds perceived delay. Mitigated
  by instant 👀 reaction and configurable `BOT_DEBOUNCE_SECONDS=0` to disable.
- **Memory for queued messages**: bounded by `max_batch_size` and idle timeout cleanup.

## Open Questions

- None at this time.
