# Tasks + sub-agents (parallel execution design)

This document proposes a simple, debuggable way to run multiple sub-agents in parallel while keeping **one** task graph (`TaskStore`) as the source of truth for orchestration.

The intent is to keep the first iteration small: **LLM-driven scheduling** (the main agent chooses what to run next) + **sub-agents update their own task status**.

## Goals

- Use `TaskStore` as the canonical DAG: tasks, dependency edges, and status.
- Let the main agent decide *what* to run next based on `TaskList.available`.
- Run multiple sub-agents concurrently (each is a fresh ReAct loop).
- Have workers produce results that are written back into `TaskStore` for downstream reuse.
- Keep intermediate artifacts ephemeral by default (sub-agents should avoid writing scratch files).
- Keep everything debuggable:
  - `TaskList` and `tasksMd` snapshots
  - optional `TaskDumpMd` to write a `tasks.md` snapshot to disk

## Non-goals (first iteration)

- Cross-process persistence / session restore.
- Strongly consistent, atomic task claiming (leases, heartbeats, worker IDs).
- Automatic conflict-free parallel code edits (file locks, merge automation).

## Conceptual model

**One orchestrator** (the main agent loop) owns planning and merging.

**Many workers** (sub-agents) execute individual tasks in parallel.

The orchestrator and workers share the same in-memory `TaskStore` instance.

### Task graph (source of truth)

- Each task has:
  - `id`
  - `content` (imperative)
  - `activeForm` (present continuous, optional)
  - `status`: `pending` | `in_progress` | `completed`
  - `blockedBy`: list of upstream task IDs
- `TaskList.available` is the computed set of task IDs that are:
  - not `completed`
  - and have all dependencies completed

## Orchestrator loop (LLM scheduling)

The main agent follows a repeated loop:

1. **Build/repair the graph** using `TaskCreate/TaskUpdate`.
2. Call `TaskList` and read:
   - `available` (ready-to-run IDs)
   - full task list (status and dependencies)
3. **Pick a batch** of up to `N` ready tasks to run in parallel.
   - Prefer tasks that are independent and likely to touch different files/modules.
4. **Spawn sub-agents** for the selected tasks.
5. **Wait for results**, then continue:
   - if tasks completed, downstream tasks become available
   - if blocked, update the plan (create new tasks or adjust dependencies)

`TaskDumpMd` is optional and is intended only for debugging (e.g., after each batch or on user request).

## Worker contract (sub-agent responsibilities)

Each sub-agent should be prompted to follow a simple contract:

1. **Execute**
   - Use tools to complete only this task.
   - Avoid modifying unrelated files.
   - Prefer not to write scratch artifacts; if needed, keep them minimal.
2. **Report**
   - Return a bounded result that can be stored verbatim in the task's `detail` (key claims + evidence/links + caveats).

Workers do not mutate the task graph directly; the orchestrator applies results with `TaskUpdate`.

## Proposed tool rewrite: parallel sub-agent runner

The existing `multi_task` tool is generic (string tasks, optional dependency indices). For tasks-based orchestration, a cleaner interface is a tool that runs **task IDs**.

### New tool: `sub_agent_batch` (recommended)

Runs a set of workers concurrently. The orchestrator decides which task IDs to run by calling `TaskList` first.

Input sketch:

```json
{
  "runs": [
    { "taskId": "12", "notes": "Optional extra constraints" },
    { "taskId": "15" }
  ],
  "maxParallel": 4
}
```

Behavior sketch:

- For each `runs[i]`:
  - start a fresh ReAct loop (no memory) with a worker prompt containing:
    - the `taskId`
    - the worker contract above
    - optional `notes`
  - provide a tool schema set that includes normal repo tools (read/search/edit/shell), optionally restricted
  - run all workers in an `asyncio.TaskGroup`, bounded by `maxParallel`

Result sketch (bounded):

```json
{
  "ok": true,
  "results": [{ "taskId": "12", "ok": true }, { "taskId": "15", "ok": false, "error": "…" }],
  "updates": [{ "id": "12", "status": "completed", "detail": "…(truncated)…", "replaceDetail": true }]
}
```

### Why a batch tool instead of calling `SubAgentRun` multiple times?

The main ReAct loop executes tool calls sequentially unless all tools are marked readonly. A batch runner is the simplest way to get true concurrency without changing the core ReAct loop.

## Concurrency hazards (and pragmatic mitigations)

### Duplicate work

Without atomic claiming, two workers can race and both start the same task.

Mitigation (MVP):

- Worker self-check via `TaskList` + early exit if not available.
- Orchestrator should avoid scheduling the same `taskId` twice in one batch.

Future improvement:

- Add an atomic `TaskClaim(taskId, workerId, leaseUntil)` tool, or embed a lease field in `TaskStore`.

### Conflicting file edits

Two workers may edit the same file concurrently.

Mitigation (MVP):

- Orchestrator selects tasks with disjoint file scopes.
- Workers are prompted to avoid cross-cutting refactors.

Future improvement:

- Add per-path locks in write/edit tools, or a central edit queue.

### Stuck `in_progress`

If a worker crashes mid-task, a task can remain `in_progress`.

Mitigation (MVP):

- Orchestrator can manually reset via `TaskUpdate(status="pending")`.

Future improvement:

- Leases + heartbeat timestamps, and an auto-reaper to reset expired leases.

## Debugging / observability

- `TaskList` includes `tasksMd` and `debugTasksMd` for quick inspection.
- `TaskDumpMd(path="tasks.md", includeDebug=true)` persists snapshots for review.
