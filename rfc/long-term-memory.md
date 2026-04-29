# RFC 008: Cross-Session Long-Term Memory

- **Status**: Implemented
- **Created**: 2026-02-06
- **PR**: [#75](https://github.com/ouro-ai-labs/ouro/pull/75)

## Problem Statement

ouro's existing memory system (short-term buffer + working-memory compression + YAML session persistence) is scoped to a single session. When the user starts a new conversation the agent has zero recall of prior decisions, preferences, or project facts. This leads to:

1. **Repeated context-setting**: Users must re-explain their coding style, preferred libraries, project conventions, etc. every session.
2. **Lost decisions**: Rationale for architectural choices made in earlier sessions is forgotten, causing the agent to re-ask or contradict past decisions.
3. **No knowledge accumulation**: Facts the agent discovers about the project (directory layout, CI quirks, deployment targets) are discarded at session end.

These issues worsen for power users who interact with the agent daily — the agent never "learns" from its own history.

## Design Goals

- **Cross-session persistence**: Memories survive process restarts and are loaded automatically on startup.
- **Agent-driven writes**: The agent decides *what* to remember, using its existing file and shell tools — no new tool API required.
- **Human-readable storage**: Memory files should be viewable and editable with any text editor, consistent with the project's YAML-file-based persistence philosophy (RFC 007).
- **Bounded growth**: An automatic consolidation mechanism prevents unbounded token usage in the system prompt.
- **Change detection**: The system can detect if memories were mutated externally (e.g., by the agent's own tool calls) to support future refresh workflows.
- **Minimal coupling**: The feature should be additive — a new `memory/long_term/` subpackage — with only lightweight integration points into the existing agent and memory manager.

## Approach

### Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                      Agent (LoopAgent)                       │
│                                                              │
│  startup: load_and_format() ──► inject into system prompt    │
│  runtime: agent uses file/shell tools to edit .md + git      │
└──────────────────┬───────────────────────────────────────────┘
                   │
        ┌──────────▼──────────┐
        │ LongTermMemoryManager│  ◄── Facade
        │    (load_and_format) │
        └──┬──────────────┬───┘
           │              │
  ┌────────▼────┐  ┌──────▼───────────────┐
  │GitMemoryStore│  │LongTermMemoryConsolidator│
  │  (read/write │  │  (LLM-based merge/prune) │
  │   + git ops) │  │                          │
  └──────────────┘  └──────────────────────────┘
           │
    ~/.ouro/memory/   (git repo)
    ├── .git/
    ├── decisions.md
    ├── preferences.md
    └── facts.md
```

### Storage: Git-Backed Markdown Files

Memories live in `~/.ouro/memory/` as free-form Markdown files, organized into three categories:

| File | Purpose |
|------|---------|
| `decisions.md` | Key decisions and their rationale |
| `preferences.md` | User preferences, coding style, workflow habits |
| `facts.md` | Factual info about projects, environments, tools |

The directory is initialized as a local git repository. Git serves two purposes:

1. **Persistence tracking**: The agent commits changes after writing, so memory updates are durable.
2. **Change detection**: By comparing HEAD at load time vs. current HEAD, the system can detect external mutations (e.g., the agent edited a file mid-session via tool calls).

Markdown was chosen over YAML (considered initially) because:
- The agent naturally produces free-form text; forcing structured YAML adds parsing friction and failure modes.
- Markdown is more flexible — the agent can decide its own heading/bullet structure per category.
- Consolidation prompts and responses are simpler without YAML escaping concerns.

### Write Path: Agent-Driven, No New Tools

The agent writes memories using its **existing file-edit and shell tools**. The system prompt instructs the agent when and how to update memory:

- **When**: user expresses a preference, an important decision is made, a new project fact is learned, or the user explicitly asks to remember something.
- **How**: edit the target `.md` file, then commit with git.

This design avoids adding a dedicated "save memory" tool. Benefits:
- Zero new tool surface area to maintain.
- The agent already knows how to use file and shell tools — no new capability needed.
- Users can inspect and edit memory files directly (they're just markdown + git).

### Read Path: System Prompt Injection

At session start, `LongTermMemoryManager.load_and_format()`:

1. Calls `GitMemoryStore.load_all()` to read all three category files and snapshot the current git HEAD.
2. Checks if consolidation is needed (see below).
3. Formats a `<long_term_memory_management>` XML block containing:
   - Current memory contents (only non-empty categories, to save tokens).
   - Instructions for when/how to update memories.
4. The block is appended to the system prompt by `LoopAgent.run()`.

### Bounded Growth: LLM-Based Consolidation

When total memory content exceeds a configurable token threshold (`LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD`, default 5000 tokens), the consolidator:

1. Formats all memories into a single text block.
2. Sends a consolidation prompt to the LLM asking it to merge duplicates, remove stale entries, and compress — targeting at least 40% reduction.
3. Parses the structured response (## headers per category) back into the three-category dict.
4. Writes the consolidated result and commits it via `GitMemoryStore.save_and_commit()`.
5. Re-snapshots HEAD so the consolidation commit itself doesn't trigger false "changed since load" signals.

Fallback behavior: if the LLM returns an unparseable response, the original memories are preserved unchanged. Missing categories in the LLM response are filled from originals.

### Change Detection

`GitMemoryStore` tracks the HEAD hash at load time (`_loaded_head`). The `has_changed_since_load()` method compares current HEAD against the snapshot. This enables future features like mid-session memory refresh (not yet implemented, but the infrastructure is ready).

## New Modules

| File | Lines | Purpose |
|------|-------|---------|
| `memory/long_term/__init__.py` | ~117 | `LongTermMemoryManager` facade — `load_and_format()`, formatting helpers |
| `memory/long_term/store.py` | ~155 | `GitMemoryStore` — git init, markdown read/write, HEAD-based change detection |
| `memory/long_term/consolidator.py` | ~132 | `LongTermMemoryConsolidator` — LLM-driven merge when entries exceed threshold |

### Integration Points (Modified Files)

| File | Change |
|------|--------|
| `config.py` | `LONG_TERM_MEMORY_ENABLED`, `LONG_TERM_MEMORY_CONSOLIDATION_THRESHOLD` |
| `utils/runtime.py` | `get_memory_dir()` returning `~/.ouro/memory/` |
| `memory/manager.py` | `long_term` property — lazy-init `LongTermMemoryManager` if enabled |
| `memory/__init__.py` | Export `LongTermMemoryManager` |
| `agent/agent.py` | Inject long-term memory section into system prompt at session start |

## Alternatives Considered

### 1. Dedicated "save memory" tool

A new tool (`save_memory(category, content)`) would give more structured control over writes.

**Rejected because**: it adds tool surface area, requires tool-call overhead (an extra LLM turn), and the agent already has file + shell tools that work well. The "no new tools" approach is simpler and more composable.

### 2. SQLite-backed storage

Consistent with some other agent frameworks that use structured databases for memory.

**Rejected because**: RFC 007 already moved session persistence *away* from SQLite toward human-readable files. Adding SQLite back for long-term memory would be inconsistent. Markdown files are simpler, diffable, and user-editable.

### 3. Single memory file instead of categories

One big `memory.md` file instead of three category files.

**Rejected because**: categories provide natural organization, make consolidation prompts clearer, and allow the agent to target specific files for updates without rewriting everything.

### 4. Automatic memory extraction (post-session analysis)

An LLM pass at session end to extract memories from the conversation.

**Rejected because**: the agent is better positioned to judge relevance *in the moment* when it learns something. Post-hoc extraction is noisier and adds latency at session teardown. The current approach (agent writes proactively during the session) is more natural and selective.

### 5. Vector-database / embedding-based retrieval

Store memories as embeddings and do semantic search at query time.

**Rejected because**: ouro prioritizes simplicity and minimal dependencies. The total memory volume for a single user is small enough (bounded by consolidation) that loading everything into the system prompt is feasible and avoids the complexity of embedding pipelines and similarity search.

## Key Design Decisions

1. **Free-form Markdown over structured YAML**: The agent produces natural text; Markdown avoids parsing/escaping failures and gives the agent freedom to structure each category as it sees fit.

2. **Git for persistence, not collaboration**: Git is used purely as a local change-tracking mechanism, not for syncing across machines. This keeps the implementation simple (no remote, no merge conflicts).

3. **Token-based consolidation threshold**: Using estimated tokens (chars / 3.5) rather than byte count gives a better proxy for system-prompt cost. The default of 5000 tokens keeps memory manageable while allowing substantial knowledge accumulation.

4. **Graceful degradation everywhere**: Every external operation (git, file I/O, LLM consolidation) is wrapped in try/except. If long-term memory fails to load, the agent continues without it. If consolidation fails, originals are preserved.

5. **Empty categories omitted from prompt**: Only non-empty categories appear in the formatted system prompt section, saving tokens for fresh users who haven't accumulated memories yet.

## Open Questions and Future Work

- **Mid-session refresh**: The `has_changed_since_load()` infrastructure exists but is not yet used to refresh memories during a session. A future iteration could reload memories when the agent detects it has committed new entries.
- **Multi-project memory**: Currently all memories share one global directory. Per-project memory directories could be useful for users working across many codebases.
- **Memory import/export**: Users might want to seed memories from a config file or share them across machines. Git remote support or a simple import command could address this.
- **Category extensibility**: The three fixed categories (decisions, preferences, facts) cover most use cases, but a plugin-style category system could be added if needed.
