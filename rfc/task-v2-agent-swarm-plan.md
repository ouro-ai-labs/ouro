# RFC: Task V2 + Agent Swarm for ouro

> **Status**: Draft
> **Author**: ouro-ai-lab
> **Date**: 2026-05-24
> **Scope**: `ouro.capabilities.tasks`, `ouro.capabilities.swarm`, `ouro.interfaces.cli`
> **Related**: claude-code Task V2 / Agent Swarm (reference implementation)

---

## 1. Summary

Upgrade ouro's single-agent `TodoTool` (memory-only, no ownership) into a **distributed task queue + multi-agent collaboration system** inspired by claude-code's Task V2 and Agent Swarm.

**Goals**:
- Persistent, shareable task lists with dependency graphs (`blocks`/`blockedBy`)
- Multi-agent task claiming and ownership (`owner` + `claim`)
- Leader/Teammate swarm roles with mailbox-based async communication
- Background task framework for fire-and-forget shell/agent execution

**Non-goals**:
- Replace `MultiTaskTool` (it stays for one-shot parallel sub-agents)
- Remote agent execution over SSH (out of scope for Phase 1–2)
- Web-based team dashboard

---

## 2. Motivation

Current `TodoTool` limitations:
- **Ephemeral**: tasks live in memory; session ends → tasks lost
- **Single-agent**: no concept of ownership or delegation
- **No dependencies**: cannot express "Task B must wait for Task A"
- **Monolithic API**: one `manage_todo_list` tool with multiple operations; LLM function calling precision is low

Claude-code's Task V2 solves these with:
- File-backed persistence + proper-lockfile concurrency
- `owner` field + atomic `claimTask` with busy-check
- `blocks`/`blockedBy` DAG + automatic availability filtering
- Split tool suite (`TaskCreate`, `TaskUpdate`, `TaskList`, `TaskGet`)

We want equivalent capabilities in ouro, adapted to Python async + SQLite.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     ouro.capabilities                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  tasks/     │  │  swarm/     │  │  tools/builtins/    │  │
│  │  store.py   │  │  mailbox.py │  │  TaskCreateTool     │  │
│  │  engine.py  │  │  roles.py   │  │  TaskUpdateTool     │  │
│  │  models.py  │  │  launcher.py│  │  TaskListTool       │  │
│  └──────┬──────┘  └──────┬──────┘  │  TaskGetTool        │  │
│         │                │         │  TaskDeleteTool     │  │
│         └────────────────┘         │  MailboxTool        │  │
│                  │                 └─────────────────────┘  │
│                  ▼                                           │
│         ┌─────────────────┐                                 │
│         │   SQLite DB     │                                 │
│         │ ~/.ouro/tasks/  │                                 │
│         │   tasks.db      │                                 │
│         └─────────────────┘                                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     ouro.core.loop                           │
│              Agent (ReAct loop, no changes)                  │
└─────────────────────────────────────────────────────────────┘
```

**Three-layer boundary preserved**:
- `ouro.core` — unchanged; `Agent` loop is agnostic to task/swarm
- `ouro.capabilities` — new `tasks/` + `swarm/` subpackages; tools wired via `AgentBuilder`
- `ouro.interfaces` — CLI flags for `--team`, `--agent-name`, `--task-list-id`

---

## 4. Data Model

### 4.1 Task

```python
# ouro/capabilities/tasks/models.py

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class Task:
    id: str                    # monotonic integer as string
    subject: str               # imperative title
    description: str
    activeForm: str | None = None
    owner: str | None = None   # agent name / id
    status: TaskStatus = TaskStatus.PENDING
    blocks: list[str] = field(default_factory=list)
    blockedBy: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=lambda: time.time())
    completed_at: float | None = None
```

### 4.2 Mailbox Message

```python
# ouro/capabilities/swarm/models.py

@dataclass
class MailboxMessage:
    id: str
    from_agent: str
    to_agent: str | None   # None = broadcast
    content: str
    timestamp: float
    read: bool = False
```

---

## 5. Storage Layer (SQLite)

### 5.1 Schema

```sql
-- ~/.ouro/tasks/{task_list_id}.db

CREATE TABLE tasks (
    id          TEXT PRIMARY KEY,
    subject     TEXT NOT NULL,
    description TEXT NOT NULL,
    activeForm  TEXT,
    owner       TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    blocks      TEXT NOT NULL DEFAULT '[]',      -- JSON array
    blockedBy   TEXT NOT NULL DEFAULT '[]',      -- JSON array
    metadata    TEXT NOT NULL DEFAULT '{}',      -- JSON object
    created_at  REAL NOT NULL,
    completed_at REAL
);

CREATE TABLE high_water_mark (
    task_list_id TEXT PRIMARY KEY,
    value        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE mailbox (
    id          TEXT PRIMARY KEY,
    from_agent  TEXT NOT NULL,
    to_agent    TEXT,
    content     TEXT NOT NULL,
    timestamp   REAL NOT NULL,
    read        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_owner ON tasks(owner);
CREATE INDEX idx_mailbox_to ON mailbox(to_agent, read);
```

### 5.2 Why SQLite over filesystem (claude-code's approach)

| Concern | Filesystem (claude-code) | SQLite (ouro) |
|---------|-------------------------|---------------|
| Concurrency | `proper-lockfile` + retry logic | `BEGIN IMMEDIATE` transactions |
| Query complexity | `readdir` + parse N files | Single SQL query |
| Dependency resolution | Python set operations | SQL `JOIN` or in-memory |
| Atomic updates | Lock + read + write + unlock | `UPDATE` in transaction |
| Python ecosystem | Extra dependency (`proper-lockfile`) | stdlib (`sqlite3`) |
| Migration | File format versioning | `PRAGMA user_version` |

**Trade-off**: SQLite requires a single writer; but `aiosqlite` + WAL mode gives excellent async concurrency for read-heavy workloads.

### 5.3 Store API

```python
# ouro/capabilities/tasks/store.py

class TaskStore:
    def __init__(self, db_path: Path) -> None: ...

    async def create(self, subject: str, description: str, ...) -> Task: ...
    async def get(self, task_id: str) -> Task | None: ...
    async def update(self, task_id: str, **fields) -> Task | None: ...
    async def delete(self, task_id: str) -> bool: ...
    async def list_all(self) -> list[Task]: ...
    async def list_available(self, agent_id: str) -> list[Task]: ...
    async def claim(self, task_id: str, agent_id: str) -> ClaimResult: ...
    async def unblock_check(self, task_id: str) -> list[str]: ...
```

---

## 6. Task Engine

### 6.1 Dependency Resolution

```python
# ouro/capabilities/tasks/engine.py

def get_available_tasks(tasks: list[Task]) -> list[Task]:
    """Return tasks that are pending, unowned, and have all blockers resolved."""
    completed_ids = {t.id for t in tasks if t.status == TaskStatus.COMPLETED}
    return [
        t for t in tasks
        if t.status == TaskStatus.PENDING
        and t.owner is None
        and all(b in completed_ids for b in t.blockedBy)
    ]
```

### 6.2 Claim with Atomic Busy-Check

```python
@dataclass
class ClaimResult:
    success: bool
    reason: Literal[
        "task_not_found",
        "already_claimed",
        "already_resolved",
        "blocked",
        "agent_busy",
    ] | None = None
    task: Task | None = None
    busy_with_tasks: list[str] | None = None
    blocked_by_tasks: list[str] | None = None
```

**Algorithm**:
1. `BEGIN IMMEDIATE`
2. Read target task
3. Check exists → `task_not_found`
4. Check owner mismatch → `already_claimed`
5. Check status == completed → `already_resolved`
6. Read all tasks; check blockers unresolved → `blocked`
7. Check agent has other open tasks → `agent_busy`
8. `UPDATE tasks SET owner = ?, status = 'in_progress' WHERE id = ?`
9. `COMMIT`

---

## 7. Tool Suite

### 7.1 TaskCreateTool

```python
class TaskCreateTool(BaseTool):
    name = "task_create"
    parameters = {
        "subject": {"type": "string"},
        "description": {"type": "string"},
        "activeForm": {"type": "string"},
        "metadata": {"type": "object"},
    }
    required = ["subject", "description"]
```

**Returns**: `{"task": {"id": "1", "subject": "..."}}`

### 7.2 TaskUpdateTool

```python
class TaskUpdateTool(BaseTool):
    name = "task_update"
    parameters = {
        "taskId": {"type": "string"},
        "subject": {"type": "string"},
        "description": {"type": "string"},
        "activeForm": {"type": "string"},
        "status": {"enum": ["pending", "in_progress", "completed", "deleted"]},
        "owner": {"type": "string"},
        "addBlocks": {"type": "array", "items": {"type": "string"}},
        "addBlockedBy": {"type": "array", "items": {"type": "string"}},
        "metadata": {"type": "object"},
    }
    required = ["taskId"]
```

**Special behavior**:
- `status: "deleted"` → `DELETE FROM tasks WHERE id = ?` + cascade cleanup of `blocks`/`blockedBy` references
- `status: "completed"` → set `completed_at = now()`
- `addBlocks` / `addBlockedBy` → bidirectional edge insertion
- Auto-set `owner` on `status: "in_progress"` if swarm enabled and owner not provided

### 7.3 TaskListTool

```python
class TaskListTool(BaseTool):
    name = "task_list"
    parameters = {}  # no input
    is_read_only = True
```

**Returns**:
```
#1 [pending] Fix authentication bug
#2 [in_progress] (alice) Refactor database layer [blocked by #1]
#3 [completed] Update README
```

**Filtering**: `blockedBy` only shows **unresolved** blockers (not completed ones).

### 7.4 TaskGetTool

```python
class TaskGetTool(BaseTool):
    name = "task_get"
    parameters = {"taskId": {"type": "string"}}
    required = ["taskId"]
    is_read_only = True
```

### 7.5 TaskDeleteTool

```python
class TaskDeleteTool(BaseTool):
    name = "task_delete"
    parameters = {"taskId": {"type": "string"}}
    required = ["taskId"]
```

### 7.6 MailboxTool (Swarm)

```python
class MailboxTool(BaseTool):
    name = "mailbox"
    parameters = {
        "operation": {"enum": ["send", "read", "mark_read"]},
        "to_agent": {"type": "string"},      # for send
        "content": {"type": "string"},       # for send
        "message_id": {"type": "string"},    # for mark_read
    }
```

---

## 8. Swarm Layer

### 8.1 Agent Identity

```python
# ouro/capabilities/swarm/identity.py

@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str      # UUID or machine-generated
    name: str          # human-readable
    team: str | None = None
    role: Literal["leader", "teammate"] = "teammate"
```

**Resolution order** (same as claude-code's `getTaskListId`):
1. `OURO_TASK_LIST_ID` env var
2. In-process teammate context
3. `OURO_TEAM_NAME` env var
4. Leader-set team name
5. Session ID fallback

### 8.2 Role Prompts

**Leader prompt injection**:
```markdown
You are the team leader. Your responsibilities:
1. Decompose user requests into tasks using `task_create`
2. Assign tasks to teammates using `task_update` with `owner`
3. Monitor progress with `task_list`
4. When a teammate completes a task, check for newly unblocked work
5. Summarize results to the user
```

**Teammate prompt injection**:
```markdown
You are a team member. Your workflow:
1. Call `task_list` to find available tasks (pending, no owner, not blocked)
2. Claim a task with `task_update` (set `owner` to your name, `status` to `in_progress`)
3. Execute the task
4. Mark complete with `task_update` (set `status` to `completed`)
5. Call `task_list` again to find next work
6. If blocked, notify leader via `mailbox`
```

### 8.3 Swarm Launcher

```python
# ouro/capabilities/swarm/launcher.py

class SwarmLauncher:
    def __init__(self, leader: ComposedAgent, store: TaskStore) -> None: ...

    async def spawn_teammate(self, name: str) -> ComposedAgent:
        """Create a new agent instance with teammate role + shared store."""
        ...

    async def run(self, task: str) -> str:
        """Leader decomposes task; teammates claim and execute; leader summarizes."""
        ...
```

**Execution model**:
- All agents run as `asyncio` coroutines in the same process
- Each agent has independent `MessageListContext` (conversation state)
- Shared `TaskStore` (SQLite) for coordination
- `MailboxTool` for async messaging

### 8.4 Lifecycle Events

| Event | Action |
|-------|--------|
| Teammate starts | Register in team file; begin `task_list` polling loop |
| Teammate claims task | `task_update` with `owner` + `status: in_progress` |
| Teammate completes | `task_update` with `status: completed` |
| Teammate crashes | Leader detects (heartbeat timeout); unassign tasks (reset to `pending`) |
| Leader terminates | Signal all teammates to exit gracefully |

---

## 9. Background Task Framework

### 9.1 Protocol

```python
# ouro/core/loop/task_framework.py

class BackgroundTask(Protocol):
    name: str
    task_type: str  # 'shell' | 'agent' | 'workflow'

    async def spawn(self, input: dict, context: TaskContext) -> str:
        """Return task_id immediately; do not block."""
        ...

    async def kill(self, task_id: str) -> None: ...
    async def get_output(self, task_id: str) -> str: ...
    async def get_status(self, task_id: str) -> TaskStatus: ...
```

### 9.2 Integration with Task V2

When a Background Task completes:
```python
# In TaskOutputTool or notification handler
if bg_task.status in ("completed", "failed", "killed"):
    # Optionally update linked Task V2 item
    if linked_task_id := bg_task.metadata.get("linked_task_id"):
        await task_store.update(
            linked_task_id,
            status="completed" if bg_task.status == "completed" else "pending",
        )
```

---

## 10. CLI Integration

### 10.1 New Flags

```bash
# Standalone with Task V2
python -m ouro.interfaces.cli.entry --task "Build a web app" --enable-tasks

# As leader of a swarm
python -m ouro.interfaces.cli.entry --task "Build a web app" \
  --team my-team \
  --agent-name leader \
  --role leader \
  --teammates 3

# As teammate
python -m ouro.interfaces.cli.entry \
  --team my-team \
  --agent-name alice \
  --role teammate
```

### 10.2 Environment Variables

| Variable | Purpose |
|----------|---------|
| `OURO_ENABLE_TASKS` | Force-enable Task V2 (default: interactive only) |
| `OURO_TASK_LIST_ID` | Explicit task list ID |
| `OURO_TEAM_NAME` | Team name for shared task list |
| `OURO_AGENT_NAME` | Agent display name |
| `OURO_AGENT_ROLE` | `leader` or `teammate` |

---

## 11. Migration Strategy

### 11.1 TodoTool → Task V2

| Phase | Action |
|-------|--------|
| 1 | Implement `tasks/` + new tool suite alongside `TodoTool` |
| 2 | `AgentBuilder` auto-injects new tools; `TodoTool` stays for compat |
| 3 | Feature flag: `AgentBuilder.with_task_v2(enabled=True)` |
| 4 | Deprecate `TodoTool` (log warning) |
| 5 | Remove `TodoTool` in major version |

### 11.2 MultiTaskTool Relationship

`MultiTaskTool` **stays unchanged**. It solves a different problem:

| Tool | Use Case | Lifetime |
|------|----------|----------|
| `MultiTaskTool` | One-shot parallel sub-agents with DAG deps | Single turn |
| `TaskCreateTool` + Swarm | Persistent, collaborative task queue | Multi-turn, multi-session |

**Future integration**: `MultiTaskTool` could create Background Tasks that write to the shared Task Store.

---

## 12. Testing Strategy

### 12.1 Unit Tests

```bash
# Task store
./scripts/dev.sh test -q test/tasks/test_store.py

# Dependency resolution
./scripts/dev.sh test -q test/tasks/test_engine.py

# Claim logic (race conditions)
./scripts/dev.sh test -q test/tasks/test_claim.py

# Tool suite
./scripts/dev.sh test -q test/tasks/test_tools.py
```

### 12.2 Integration Tests

```bash
# Two-agent swarm on same SQLite db
./scripts/dev.sh test -q test/swarm/test_two_agent_collaboration.py

# Task persistence across process restart
./scripts/dev.sh test -q test/tasks/test_persistence.py
```

### 12.3 Smoke Tests

```bash
# Single agent with Task V2
python -m ouro.interfaces.cli.entry --task "Plan a trip: create 3 tasks, complete them" --enable-tasks --verify

# Mini swarm
python -m ouro.interfaces.cli.entry --task "Write a README and a test file" --team smoke-test --teammates 1
```

---

## 13. Implementation Phases

### Phase 1: Task V2 Core (Week 1–2)

- [ ] `ouro/capabilities/tasks/models.py` — Task dataclass + TaskStatus
- [ ] `ouro/capabilities/tasks/store.py` — SQLite store with aiosqlite
- [ ] `ouro/capabilities/tasks/engine.py` — CRUD + dependency resolution + claim
- [ ] `ouro/capabilities/tools/builtins/task_tools.py` — TaskCreate/Update/List/Get/Delete
- [ ] Wire into `AgentBuilder` (feature-flagged, alongside TodoTool)
- [ ] Unit tests for store + engine
- [ ] `./scripts/dev.sh check` passes

### Phase 2: Agent Swarm (Week 3–4)

- [ ] `ouro/capabilities/swarm/models.py` — AgentIdentity, MailboxMessage
- [ ] `ouro/capabilities/swarm/mailbox.py` — SQLite-backed mailbox
- [ ] `ouro/capabilities/swarm/roles.py` — Leader/Teammate prompt templates
- [ ] `ouro/capabilities/swarm/launcher.py` — SwarmLauncher
- [ ] `MailboxTool` — send/read/mark_read
- [ ] CLI flags: `--team`, `--agent-name`, `--role`, `--teammates`
- [ ] Integration tests: 2-agent collaboration
- [ ] Smoke test with real swarm

### Phase 3: Background Task + Polish (Week 5–6)

- [ ] `ouro/core/loop/task_framework.py` — BackgroundTask Protocol
- [ ] `LocalShellTask`, `LocalAgentTask` implementations
- [ ] `TaskOutputTool` — poll/wait for background task completion
- [ ] Link Background Tasks to Task V2 items
- [ ] Process lifecycle management (heartbeat, unassign on crash)
- [ ] Documentation: `docs/tasks.md`, `docs/swarm.md`
- [ ] Deprecation notice for TodoTool
- [ ] `./scripts/dev.sh check` + full test suite

---

## 14. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| SQLite contention under high concurrency | Medium | WAL mode + `BEGIN IMMEDIATE` + benchmark early |
| LLM confusion between TodoTool and Task tools | Medium | Clear tool descriptions; feature flag prevents both active |
| Swarm agents deadlock (circular claim) | Low | Claim timeout + heartbeat; leader can force-unassign |
| Memory bloat (many agents in one process) | Medium | Limit max teammates; support out-of-process in future |
| Breaking existing TodoTool users | High | Gradual deprecation; keep TodoTool for 2+ minor versions |

---

## 15. Open Questions

1. **Should we support claude-code's filesystem-based storage as an alternative backend?**
   - Pro: compatibility with claude-code task lists
   - Con: extra complexity; SQLite is strictly better for Python
   - **Tentative**: No; focus on SQLite. Revisit if cross-tool compatibility becomes a requirement.

2. **How do we handle agent "crashes" in a single-process model?**
   - Option A: `asyncio` task exception handler + leader polling
   - Option B: Heartbeat table in SQLite (`last_seen` timestamp)
   - **Tentative**: Option B; simpler and works across process restarts.

3. **Should Task V2 be enabled by default in interactive mode?**
   - claude-code: yes (non-interactive only with env var)
   - ouro: **Tentative**: yes in interactive; no in non-interactive (SDK users may prefer simpler TodoTool)

---

## 16. References

- claude-code `src/utils/tasks.ts` — Task store + claim logic
- claude-code `src/tools/TaskCreateTool/` — Tool prompts + schemas
- claude-code `src/tools/TaskUpdateTool/` — Status workflow + dependency management
- claude-code `src/Task.ts` — Background task types + state machine
- ouro `ouro/capabilities/todo/state.py` — Current TodoList implementation
- ouro `ouro/capabilities/tools/builtins/multi_task.py` — MultiTaskTool (parallel sub-agents)
- ouro `ouro/capabilities/builder.py` — AgentBuilder wiring

---

## Appendix: Directory Layout

```
ouro/
├── ouro/capabilities/
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── store.py
│   │   ├── engine.py
│   │   └── constants.py
│   ├── swarm/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── mailbox.py
│   │   ├── roles.py
│   │   ├── launcher.py
│   │   └── identity.py
│   └── tools/builtins/
│       ├── task_create.py
│       ├── task_update.py
│       ├── task_list.py
│       ├── task_get.py
│       ├── task_delete.py
│       └── mailbox.py
├── test/tasks/
│   ├── test_store.py
│   ├── test_engine.py
│   ├── test_claim.py
│   └── test_tools.py
├── test/swarm/
│   └── test_two_agent_collaboration.py
└── docs/
    ├── tasks.md
    └── swarm.md
```
