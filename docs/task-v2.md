# Task V2 (Persistent Task Management)

Task V2 is a SQLite-backed persistent task store with dependency graphs, designed for multi-agent coordination and complex workflow management.

## Overview

- **Persistent**: Tasks survive agent restarts (stored in SQLite)
- **Dependency-aware**: Tasks can block/unblock other tasks
- **Atomic claim**: Prevents double-assignment in multi-agent scenarios
- **Opt-in**: Enabled via `AgentBuilder.with_task_v2()` — does not affect existing agents

## Quick Start

```python
from ouro.capabilities.builder import AgentBuilder
from ouro.core.llm import LiteLLMAdapter

llm = LiteLLMAdapter(model="openai/gpt-4o", api_key="sk-...")

agent = (
    AgentBuilder()
    .with_llm(llm)
    .with_task_v2(enabled=True)  # Enable Task V2
    .build()
)
```

The agent now has 5 additional tools:

| Tool | Readonly | Purpose |
|------|----------|---------|
| `task_create` | No | Create a task with subject, description, optional dependencies |
| `task_update` | No | Update status, owner, dependencies, or metadata |
| `task_list` | Yes | List all tasks with status summary |
| `task_get` | Yes | Get full details of a specific task |
| `task_delete` | No | Permanently delete a task and clean up references |

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `TASK_V2_ENABLED` | `false` | Enable persistent task store |
| `TASK_V2_STORE_PATH` | `~/.ouro/tasks/default.db` | SQLite database path |

Custom path:

```python
agent = (
    AgentBuilder()
    .with_llm(llm)
    .with_task_v2(enabled=True, store_path="/custom/path/tasks.db")
    .build()
)
```

## Task Lifecycle

```
pending → in_progress → completed
   ↓
deleted
```

- **pending**: Task is created but not started
- **in_progress**: Task is claimed by an agent
- **completed**: Task is finished
- **deleted**: Task is permanently removed

## Dependency Management

Tasks can depend on other tasks:

```python
from ouro.capabilities.tasks import TaskStore

store = TaskStore("~/.ouro/tasks/default.db")

# Create a blocker task
blocker = store.create(subject="Setup DB", description="Create database schema")

# Create a task that depends on the blocker
task = store.create(
    subject="Seed data",
    description="Insert initial data",
    blockedBy=[blocker.id]
)

# task is not available until blocker is completed
available = store.list_available()  # Does not include task

# Complete the blocker
store.update(blocker.id, status="completed")

# Now task is available
available = store.list_available()  # Includes task
```

## Programmatic API

### Direct Store Access

```python
from ouro.capabilities.tasks import TaskStore, TaskStatus

store = TaskStore("~/.ouro/tasks/default.db")

# Create
task = store.create(
    subject="Refactor auth",
    description="Move auth logic to middleware",
    metadata={"priority": "high"}
)

# Read
print(store.get(task.id))

# Update
store.update(task.id, status=TaskStatus.IN_PROGRESS, owner="alice")

# Claim (atomic)
result = store.claim(task.id, owner="alice")
if result.success:
    print(f"Claimed task #{task.id}")
else:
    print(f"Failed: {result.error}")

# Unassign
store.unassign(task.id)

# Delete
store.delete(task.id)

# List
all_tasks = store.list_all()
available = store.list_available()  # Pending + unowned + unblocked
```

### Task Model

```python
from dataclasses import dataclass
from ouro.capabilities.tasks import TaskStatus

@dataclass
class Task:
    id: str
    subject: str
    description: str
    activeForm: str | None
    status: TaskStatus  # pending, in_progress, completed, deleted
    owner: str | None
    blocks: list[str]       # Tasks this task blocks
    blockedBy: list[str]    # Tasks blocking this task
    metadata: dict
    createdAt: str
    updatedAt: str
```

## Multi-Agent Coordination

Task V2 is designed for swarm scenarios:

```python
# Agent 1 claims a task
result = store.claim("1", owner="agent-1")

# Agent 2 cannot claim the same task
result = store.claim("1", owner="agent-2")
# ClaimResult(success=False, error="Task #1 is already claimed by agent-1")

# Agent 1 completes the task
store.update("1", status=TaskStatus.COMPLETED)

# Now agent 2 can claim dependent tasks
for task in store.list_available():
    if "1" in task.blockedBy:
        store.claim(task.id, owner="agent-2")
```

## Persistence

Tasks are stored in SQLite with WAL mode:

- **Location**: `~/.ouro/tasks/default.db` (configurable)
- **Format**: SQLite with WAL journal mode
- **Migration**: Auto-created on first use; schema managed internally
- **Backup**: Copy the `.db` file to back up tasks

## Limitations (Phase 1)

- No built-in task scheduling or cron-like triggers
- No web UI for task management
- Task list is not paginated (all tasks loaded in memory for `task_list`)
- No automatic task retry or failure recovery

## Roadmap

- **Phase 2**: Agent Swarm coordination, `task_claim` tool, task delegation
- **Phase 3**: Web UI, task analytics, advanced filtering
