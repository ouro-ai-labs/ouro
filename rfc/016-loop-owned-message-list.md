# RFC 016: Loop-owned MessageList and long-term-only memory boundary

- Status: Superseded
- Authors: OpenAI Codex
- Date: 2026-04-28

## Summary
> Note: this RFC describes an earlier design direction that was not
> adopted as written. The implemented refactor keeps `ProgressSink`,
> keeps `TuiProgressSink`, and uses hook-driven transient loop message
> state with `MemoryHook` / `MemoryManager` owning persisted conversation
> history when memory is enabled. Treat this document as historical
> context rather than the current contract.

Refactor the agent runtime so `ouro.core.loop.Agent` owns one canonical mutable `MessageList` for the current run, and all message mutations happen through hook lifecycle methods against that shared handle. In the same change, remove `ProgressSink` as a parallel side channel and shrink `ouro.capabilities.memory` so it owns long-term recall plus session persistence only, not the in-run conversation log.

## Problem

Today the loop in `ouro/core/loop/agent.py` keeps a local `messages: list[LLMMessage]`, but that list is not the real source of truth once `MemoryHook` is present.

Concrete examples:

- `Agent.run()` initializes a local `messages` list, but `MemoryHook.before_call()` ignores that list and returns `memory.get_context_for_llm()` instead.
- System prompt and user input are not added by the loop. They are inserted into `MemoryManager` from `ComposedAgent.run()`, then injected into every LLM call by `MemoryHook`.
- Compaction rewrites `MemoryManager.short_term` in place via `apply_compression()`, while the loop's local `messages` list remains untouched.
- Session resume happens outside the loop through `ComposedAgent.load_session()` and `MemoryManager.from_session()`.
- TUI output uses `ProgressSink`, which duplicates hook-style observation flow through a separate protocol.

This mixes three different concerns inside memory:

1. the current run's conversation log,
2. compaction and token-accounting for that log,
3. cross-session long-term recall and persistence.

That makes the loop contract hard to reason about because "what the loop holds" can differ from "what the LLM sees", and UI events flow through a separate mechanism from message lifecycle events.

## Goals

- Make the loop-owned `MessageList` the single source of truth for current conversation state.
- Ensure all message mutations flow through hooks against the same mutable handle.
- Fold `ProgressSink` behavior into hook lifecycle and scope methods.
- Reduce `ouro.capabilities.memory` to long-term recall plus session persistence responsibilities.
- Preserve existing CLI, TUI, bot, resume, verification, and compaction behavior.

## Non-goals

- Changing LLM provider behavior or request/response schemas.
- Changing tool schemas or tool execution semantics.
- Changing the persisted session YAML schema.
- Introducing user-facing CLI or bot behavior changes.
- Doing the refactor incrementally across multiple compatibility layers.

## Proposed Behavior (User-Facing)

The intended outcome is no user-visible behavior change.

- CLI / UX changes: none expected. `ouro --task`, interactive TUI, bot flows, `--resume`, and verification should behave the same.
- Config changes: none.
- Output / logging changes: none by intent, except internal implementation moves from `ProgressSink` to hooks.

Internally:

- `Agent.run()` owns a single mutable `MessageList`.
- Hooks receive that same handle for all lifecycle points that may mutate state.
- Session restore, system prompt bootstrap, user message insertion, assistant append, tool-result append, and compaction prefix rewrite all happen via hook-driven mutations.
- TUI printing and spinners are implemented as a hook instead of a separate progress sink.
- Memory retains long-term recall and session persistence, while short-term in-run conversation state is no longer owned by `MemoryManager`.

## Invariants (Must Not Regress)

- `--resume <id>` continues to restore prior conversation and make it visible to the next turn.
- Cache-safe compaction from RFC 012 still triggers at the same threshold and produces the same summary-message shape.
- Ralph verification from RFC 006 still retries on incomplete STOP responses and injects feedback correctly.
- Long-term memory promotion via `<long_term_memories>` extraction still happens during compaction.
- Parallel execution of multiple read-only tools remains unchanged.

## Design Sketch (Minimal)

### 1. New loop-owned `MessageList`

Add `ouro/core/loop/messages.py` with a mutable wrapper around `list[LLMMessage]`:

- `append()`
- `extend()`
- `replace_range()`
- `snapshot()`
- read access via `__len__`, `__iter__`, `__getitem__`

The loop constructs one `MessageList` per run and passes it to hooks. The loop itself stops mutating the underlying message list directly after construction.

### 2. Hook protocol becomes the full lifecycle contract

Update `ouro/core/loop/protocols.py` so hooks can both mutate and observe the run:

Mutation-oriented methods receive `messages: MessageList`:

- `on_run_start(ctx, messages)`
- `on_user_message(ctx, messages, content)`
- `before_call(ctx, messages, tools) -> list[LLMMessage]`
- `after_call(ctx, messages, response)`
- `on_tool_results(ctx, messages, calls, results)`
- `on_compact_check(ctx, messages)`
- `on_iteration_end(ctx, messages, response, finished)`
- `on_run_end(ctx, messages, final_answer)`

Observation / UI methods become hook methods too:

- `on_thinking(...)`
- `on_assistant_text(...)`
- `on_tool_call(...)`
- `on_tool_result(...)`
- `on_final_answer(...)`
- `on_unfinished_answer(...)`
- `on_info(...)`
- `scope_llm_call(...)`
- `scope_tool_call(...)`
- `scope_compaction(...)`

`CompactionDecision.on_summary` also changes to accept `messages: MessageList` so the hook can rewrite the canonical list in place.

### 3. Agent loop owns sequencing, hooks own mutations

Rewrite `core/loop/agent.py` so:

- `run()` no longer accepts `initial_messages`; the task text is treated as data that a hook can inject during `on_run_start`.
- The loop creates a `MessageList` and passes it to all hook methods.
- Assistant messages and tool results are appended by hooks, not by loop-local `messages.append()` or `messages.extend()`.
- Spinner scopes are driven through hook async context-manager methods rather than `ProgressSink`.
- Compaction leaves rewrite policy to the hook by calling `decision.on_summary(summary, usage, messages)`.

### 4. Memory splits into hook-internal conversation logic vs durable memory

Refactor `ouro.capabilities.memory` so:

- Session store / lookup helpers move into `memory/session.py`.
- Conversation-specific compaction and token accounting move into a hook-internal module such as `memory/conversation.py`.
- `MemoryHook` becomes the only component that owns session persistence, resume loading, compaction threshold checks, compaction prefix rewrite, and long-term extraction integration.
- `MemoryManager` is slimmed down or renamed to reflect long-term-only scope.

### 5. TUI becomes a hook

Replace `TuiProgressSink` with `TuiHook` in `ouro.interfaces.tui`, preserving the same UX and spinner behavior while using hook lifecycle methods.

## Alternatives Considered

- Option A: keep `MemoryManager` as the short-term source of truth and formally document the loop's local message list as advisory. Rejected because it preserves split ownership and unclear invariants.
- Option B: migrate incrementally with both a loop-owned message list and memory-owned shadow state for compatibility. Rejected because it prolongs dual-state bugs and makes behavior harder to validate.
- Option C: keep `ProgressSink` for UI while only moving message ownership. Rejected because it preserves two parallel event systems instead of one hook contract.

## Test Plan

- Unit tests:
  - Add tests for `MessageList` mutation semantics.
  - Add tests for hook-chain mutation order against a shared `MessageList`.
  - Add tests for compaction prefix rewrite through `CompactionDecision.on_summary(..., messages)`.
  - Add tests for session resume happening in `on_run_start`.
  - Update direct loop tests to the new `Agent.run()` and hook contracts.
- Targeted tests to run locally:
  - `./scripts/dev.sh test -q test/test_parallel_tools.py`
  - `./scripts/dev.sh test -q test/test_reasoning_effort.py`
  - `./scripts/dev.sh test -q test/test_ralph_loop.py`
  - `./scripts/dev.sh test -q test/memory/`
- Smoke run (one real CLI run):
  - `python -m ouro.interfaces.cli.entry --task "<task>"`
  - `python -m ouro.interfaces.cli.entry --task "<task>" --verify`
  - `python -m ouro.interfaces.cli.entry --resume latest`

## Rollout / Migration

- Backward compatibility:
  - User-facing behavior should stay stable.
  - Internal Python APIs around `ProgressSink`, `MemoryManager` short-term APIs, and `Agent.run(initial_messages=...)` will change in one PR.
- Migration steps (if any):
  - Update first-party hooks and interfaces in the same PR.
  - Update tests and layer documentation in the same PR.
  - Document removed internal APIs in the PR description.

## Risks & Mitigations

- Silent compaction semantics drift.
  - Mitigation: add focused compaction rewrite tests and compare summary-message shape with existing behavior.
- Session restore timing changes when moving from `load_session()` mutation into `on_run_start`.
  - Mitigation: add resume regression tests and TUI smoke checks.
- Hook ordering becomes more important because all mutations flow through hooks.
  - Mitigation: document ordering and add explicit tests for bootstrap/memory/verification/TUI interaction.
- Interface-layer code may still depend on old `memory.short_term` and `memory.get_stats()` shapes.
  - Mitigation: preserve compatibility helpers on the composed agent or replacement memory/session facade where needed.

## Open Questions

- Should the slimmed durable-memory class be renamed from `MemoryManager` to `LongTermMemory`, or should the old name be kept temporarily for SDK stability?
- Should session persistence expose a lightweight stats/history facade to reduce churn in TUI and bot code that currently reads `memory.short_term` directly?
- Should `on_user_message` exist as a distinct hook, or should bootstrapping remain entirely inside `on_run_start` for one-shot and multimodal flows?
