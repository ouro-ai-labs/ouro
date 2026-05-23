# RFC: Letta-Inspired Improvements to LongTermMemoryManager

- Status: Draft
- Authors: yixin
- Date: 2026-05-23

## Summary

Borrow two ideas from Letta/MemGPT to make ouro's long-term memory work without any external embedder: (1) a `conversation_search` tool backed by SQLite FTS5 over historical messages (recall memory), and (2) named, size-limited memory **blocks** edited via dedicated tools instead of a single `memory.md` file edited via generic `Edit`/`Write`. Both changes are additive, zero new model dependencies, and let users get useful cross-session memory without `MEM0_ENABLED=true` (which currently requires an OpenAI key for the embedder).

## Problem

`LongTermMemoryManager` (RFC 008) stores durable knowledge in `~/.ouro/memory/memory.md` + daily files and relies on the LLM editing them with generic file tools. Two real-world gaps:

1. **No way to search past conversations.** Once a session ends or is compacted, the agent cannot recall *what was said*. The only escape today is enabling mem0 — which broke production (see traceback below) because mem0's default OpenAI embedder requires `OPENAI_API_KEY`, and our deployment only has Anthropic credentials.

   ```
   openai.OpenAIError: Missing credentials. Please pass an `api_key`, ...
     File ".../ouro/capabilities/memory/store/mem0_memory_store.py", line 152
     File ".../mem0/embeddings/openai.py", line 35
   ```

2. **Memory file is unbounded and unstructured.** `memory.md` grows monotonically until the threshold-based consolidator fires, and the LLM has to read the whole file → diff → write back for every update. There's no notion of "this block is about the user, this block is about the project" with independent size budgets.

## Goals

- Provide cross-session recall of past conversation content **without requiring an embedder**.
- Replace the implicit "Edit memory.md" flow with explicit, bounded memory tools that fail loudly when limits are exceeded.
- Stay backward-compatible: existing `~/.ouro/memory/memory.md` and daily files keep working; the new tools are opt-in.
- Zero new external model dependencies (no embedder, no vector DB).

## Non-goals

- Replacing mem0 for users who *do* want semantic search across millions of memories.
- Vector / archival memory tier (Letta's third layer). Users who need that can keep using mem0.
- Multi-agent shared blocks. ouro has no multi-agent runtime today; adding shared blocks is premature.
- Changing `CompactionManager` behavior. Memory pressure integration is out of scope for the first cut.

## Proposed Behavior (User-Facing)

### CLI / UX

No new CLI flags. Two new builtin tools become visible to the agent:

- `conversation_search(query: str, session_id: str | None = None, limit: int = 5)` — keyword search over all persisted messages. Returns excerpts with `session_id`, `timestamp`, `role`, `content_snippet`.
- `memory_block_edit(block: str, operation: "replace" | "append", content: str, old: str | None = None)` — edit a named block. Fails if the block would exceed its token budget.

Block layout under `~/.ouro/memory/blocks/`:

```
~/.ouro/memory/
├── memory.md              # legacy, still loaded if present
├── 2026-05-23.md          # legacy daily, unchanged
└── blocks/
    ├── user.md            # ~2KB cap — user identity, preferences
    ├── project.md         # ~4KB cap — durable project facts
    └── scratch.md         # ~8KB cap — recent decisions / WIP context
```

### Config

```
LONG_TERM_MEMORY_ENABLED=true     # already exists
LTM_BLOCKS_ENABLED=true           # new, default false (opt-in)
LTM_CONVERSATION_SEARCH_ENABLED=true  # new, default false (opt-in)
LTM_BLOCK_BUDGETS=user:2000,project:4000,scratch:8000  # tokens
```

When `LTM_BLOCKS_ENABLED=true`, block contents are injected into the system prompt in place of `memory.md` (legacy file still appended if it exists, to preserve old data during migration).

### Output / logging

- One log line per `memory_block_edit` call: `block=user op=replace tokens=1820/2000`.
- One log line per `conversation_search` call with hit count.

## Invariants (Must Not Regress)

- Existing `~/.ouro/memory/memory.md` + daily file behavior unchanged when both new flags are off.
- `Config.MEM0_ENABLED` remains the gate for mem0; this RFC does not touch the mem0 code path.
- No new imports from `ouro.interfaces` into `ouro.capabilities` (import-linter contract).
- All new I/O is async or routed through `asyncio.to_thread`; no blocking calls on the loop hot path.
- SQLite FTS index is created lazily on first write; absence of the index file is not an error.

## Design Sketch (Minimal)

### Recall memory (`conversation_search`)

- New `ouro/capabilities/memory/recall/sqlite_fts.py`: thin wrapper around `sqlite3` with FTS5 virtual table:
  ```sql
  CREATE VIRTUAL TABLE messages USING fts5(
      session_id, role, content, timestamp UNINDEXED
  );
  ```
- Hook into `YamlFileMemoryStore.save_message` (and `Mem0MemoryStore.save_message` for parity) to upsert into the FTS index. This is the *only* edit to existing stores.
- New builtin tool `ouro/capabilities/tools/builtins/conversation_search.py` implementing `BaseTool`, wired into `cli/factory.py`'s default toolset.
- Index lives at `~/.ouro/memory/recall.db`.

### Memory blocks

- New `ouro/capabilities/memory/blocks/` subpackage:
  - `store.py` — read/write/list blocks from `blocks/*.md`, enforce token budget via existing `TokenTracker`-compatible counter.
  - `__init__.py` — `MemoryBlockManager` facade with `load_and_format()` returning a system-prompt section.
- New tool `ouro/capabilities/tools/builtins/memory_block_edit.py`.
- `LongTermMemoryManager.load_and_format()` gains a branch: if `LTM_BLOCKS_ENABLED`, render block contents; otherwise current behavior.

### Layering

All new code lives in `ouro.capabilities.memory.*` and `ouro.capabilities.tools.builtins.*`. Interfaces layer only changes in `cli/factory.py` (toolset registration). Matches the layer contract in `ouro/CLAUDE.md`.

## Alternatives Considered

- **A. Switch to mem0 with HuggingFace embedder.** Solves the OpenAI-key issue but adds heavy deps (`sentence-transformers`, torch) and still doesn't fix `memory.md` editing ergonomics. Rejected.
- **B. Adopt Letta wholesale.** Letta is a separate server with its own DB and agent runtime. Too much surface area for our single-process bot. Rejected.
- **C. Vector recall via local Chroma.** Smaller than mem0 but still requires an embedder. Rejected per "no new model deps" goal.
- **D. Do nothing, document `MEM0_ENABLED=false` as the answer.** Cheapest, but leaves the "search past conversations" gap. Rejected.

## Test Plan

- Unit tests:
  - `test/memory/test_sqlite_fts.py` — index create/upsert/query/empty-db cases.
  - `test/memory/test_blocks.py` — block budget enforcement (replace exceeds limit → raises), append vs replace semantics, missing-block fallback.
  - `test/tools/test_conversation_search_tool.py` — tool contract, scoping by `session_id`, hit-formatting.
  - `test/tools/test_memory_block_edit_tool.py` — tool contract, budget violation surfaces as actionable error to the LLM.
- Targeted runs:
  - `./scripts/dev.sh test -q test/memory/ test/tools/`
  - `./scripts/dev.sh importlint`
- Smoke run:
  - `python main.py --task "remember that I prefer rust over go, then in a follow-up session ask what language I prefer"` across two `ouro-cli` invocations with `LTM_BLOCKS_ENABLED=true`.

## Rollout / Migration

- Both features ship behind feature flags, default off. Existing users see no change.
- When `LTM_BLOCKS_ENABLED=true` is set the first time, `memory.md` is **not** auto-migrated — its contents are still loaded into the system prompt alongside the blocks until the user (or agent) moves them. A one-shot helper `python -m ouro.capabilities.memory.blocks.migrate` can split `memory.md` into block files; documented but not run automatically.
- Rollback: flip flags off; new files in `blocks/` and `recall.db` are inert when disabled.

## Risks & Mitigations

- **FTS index drift** (rows missing if write fails mid-flight): wrap upsert in best-effort try/except, log warnings; recall is non-critical so degradation is acceptable.
- **Token-budget enforcement misjudges size** if we use a cheap tokenizer: prefer `litellm.token_counter` shared with `TokenTracker` so the count matches what the loop sees.
- **Tool sprawl**: two new builtins is small; gate via `LTM_BLOCKS_ENABLED` and `LTM_CONVERSATION_SEARCH_ENABLED` so they're not always advertised.
- **Concurrent writes to SQLite from bot multi-conversation traffic**: open with `isolation_level=None` + `PRAGMA journal_mode=WAL`; or serialize behind an `asyncio.Lock` per process.

## Open Questions

- Should `conversation_search` index *messages* or *compacted summaries* or both? Indexing raw messages gives best recall but more storage; summaries are smaller but lossy.
- Do we expose block edits to the LLM via one tool with an `operation` arg, or two tools (`memory_block_replace` / `memory_block_append`)? Two tools is more discoverable; one tool is fewer schema tokens. Default to two for now.
- Should we add a "memory pressure" hook (Letta's killer feature) as a follow-up RFC, or fold it in here? Recommend follow-up — keeps this RFC scoped.
