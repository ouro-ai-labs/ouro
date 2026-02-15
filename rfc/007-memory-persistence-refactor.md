# RFC 007: Memory Persistence Refactor — YAML Files + Session Recovery

## Status

Implemented

## Problem Statement

The existing memory persistence layer uses SQLite (`aiosqlite`) with a single `sessions` table storing JSON blobs. While functional, this creates several issues:

1. **Opaque storage**: Session data is not human-readable or editable without SQL tools
2. **Tight coupling**: `MemoryManager` depends directly on `MemoryStore` (SQLite), making it hard to swap backends
3. **No session recovery**: Users cannot resume previous sessions from CLI or interactive mode
4. **Extra dependency**: `aiosqlite` adds a runtime dependency for a feature that can be handled with flat files

## Design Goals

- **Human-readable persistence**: Session files should be viewable and editable with any text editor
- **Backend abstraction**: Decouple persistence interface from implementation
- **Session recovery**: Enable resuming previous sessions via CLI (`--resume`) and interactive (`/resume`)
- **Consistency**: Use YAML format, consistent with `.ouro/models.yaml`
- **Simplicity**: Remove SQLite dependency entirely (no migration needed)

## Approach

### Abstract Backend Interface

Introduced `MemoryStore` ABC in `memory/backend.py` with standard CRUD methods:
- `create_session()`, `save_message()`, `save_memory()`
- `load_session()`, `list_sessions()`, `delete_session()`, `get_session_stats()`

### Shared Serialization

Extracted serialization logic into `memory/serialization.py`:
- `serialize_message()` / `deserialize_message()` for `LLMMessage`

### YAML File Backend

`YamlFileMemoryStore(MemoryStore)` in `memory/yaml_backend.py`:
- **Directory structure**: `.ouro/sessions/YYYY-MM-DD_<uuid[:8]>/session.yaml`
- **Index file**: `.ouro/sessions/.index.yaml` maps UUID to directory name, lazily rebuilt
- **Atomic writes**: Write to `.tmp` then `os.replace()` for crash safety
- **Write lock**: `asyncio.Lock()` serializes concurrent writes
- **Async I/O**: Uses `aiofiles` for reads/writes, `asyncio.to_thread` for filesystem metadata

### Session Recovery

- **CLI**: `--resume [session_id|latest]` loads a previous session before running
- **Interactive**: `/resume [session_id]` command (no args lists recent sessions)
- **Prefix matching**: Session IDs can be specified by prefix (e.g., first 8 chars)

## Alternatives Considered

1. **Keep SQLite, add YAML export**: More complex, two formats to maintain
2. **JSON files**: Less human-readable than YAML for multiline content
3. **SQLite migration path**: Unnecessary complexity since the feature is new and few users have existing sessions

## Key Design Decisions

- **No migration**: SQLite data is not migrated. Sessions stored in the old format are simply no longer accessible through the new API.
- **Flat YAML per session**: Each session is a single YAML file rather than splitting into multiple files. This keeps the structure simple while remaining readable.
- **Index file**: An `.index.yaml` file enables O(1) UUID lookup without scanning all directories. It is lazily rebuilt if missing or corrupted.
- **`MemoryManager` owns the default**: If no backend is passed, `MemoryManager` creates a `YamlFileMemoryStore()` automatically. This preserves backward compatibility.
