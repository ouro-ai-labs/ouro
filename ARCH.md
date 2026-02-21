# Architecture v1: Task Board + Fanout

Ouro is built around **ReAct loops**: the agent reasons, uses tools, observes results, and repeats.

v1 orchestration is intentionally minimal:
- LLM does planning and synthesis.
- Runtime does only mechanical scheduling + artifact persistence.

## Learnings From Claude Code Tasks

Public writeups of Claude Code's evolution from "todos" to "tasks" strongly support a
control-plane oriented design:

- Tasks are a first-class state primitive (not a second agent loop).
- Tasks carry dependency metadata (`blockedBy` / `blocks`) and a small set of fields
  suitable for mechanical scheduling (status/owner/etc).
- Tasks are persisted on disk and can be shared across sub-agents; changes can be broadcast across
  multiple Claude Code sessions when they share the same task list id (implementation detail).
- Claude Code added lifecycle operations like task deletion, plus configuration to enable/disable
  tasks, which implies tasks are not "just prompt text" but managed state.
- The "hydration pattern"
  keeps an external spec as the durable source of truth, then hydrates tasks into a session.

This v1 follows that same idea, but keeps the IR and runtime as small as possible.

## Primitives

Orchestration should be composed from small primitives in the manager ReAct loop:

- `task_board`: create/list/get/update tasks; encode dependencies; persist to `tasks.md`.
- `multi_task` (fanout): run N worker ReAct loops in parallel; return `summary + artifacts` per task.

Avoid a monolithic `orchestrate` tool that runs a second "manager agent loop" inside a tool.

## `tasks.md` (Minimal IR)

`tasks.md` is the persistent blueprint and audit trail.
For deterministic parsing, it SHOULD contain a single fenced JSON block:

```json
{
  "version": 1,
  "goal": "One sentence goal",
  "tasks": [
    {
      "id": "T0",
      "status": "pending",
      "owner": null,
      "blocked_by": [],
      "subject": "Extract section headings",
      "description": "From user:/path/to/paper.pdf, extract up to 8 top-level headings.",
      "active_form": "Extracting section headings",
      "metadata": {"source": "paper.pdf"},
      "summary": "",
      "artifacts": [],
      "errors": ""
    }
  ]
}
```

Allowed `status`: `pending | in_progress | completed | failed`.

We store only `blocked_by` edges. The inverse (`blocks`) is derivable.

For very large graphs or multi-writer scenarios, an alternative representation is "one JSON file per
task" plus a small index. This reduces merge conflicts, but is not required for v1.

## Persistence Model (Hydration/Sync)

`tasks.md` is the durable spec. The in-memory task board is session-scoped state.

Hydration/sync rules:
- At the start of a run (or a new session), hydrate `tasks.md` into the task board.
- The manager may mutate the task board (status, dependencies, owner, etc).
- After each mutation (or at fanout barriers), sync back to `tasks.md`.

This preserves determinism and avoids relying on chat context for orchestration state.

Important: "hydration" is about loading orchestration state into the runtime (and optionally into
the LLM-visible context). Persistence alone does not guarantee the model will remember state across
sessions unless the runtime re-hydrates it.

## Optional Store: Claude-Like Task List Directory

Claude Code Tasks appears to back a "task list" with a directory containing one JSON file per task.
To apply the same implementation property to Ouro, `task_board` supports an optional "dir" store:

- Use `task_list_id=<id>` to store in `~/.ouro/tasks/<id>/` (cross-session / multi-process friendly).
- Or set `OURO_TASK_LIST_ID=<id>` in the environment to make it the default.
- Use `store="dir"` + `path=<dir>` to store in an arbitrary directory (useful for tests).

Directory layout:

```
~/.ouro/tasks/<task_list_id>/
  .lock
  .highwatermark
  _meta.json
  _groups.json
  <task_id>.json
  <task_id>.json
```

Each task file includes `blockedBy` plus a derived `blocks` list, mirroring the dependency metadata
style used by Claude Code Tasks. Ouro also persists `summary/artifacts/errors` alongside those fields.

Implementation notes:
- In the `dir` store, `create/update/delete` operate on per-task JSON tickets (not a full rewrite of
  the directory). This is important for multi-session correctness.
- `.highwatermark` provides monotonic task id allocation under concurrent creators.

Optional cleanup:
- Set `OURO_TASKS_AUTO_CLEANUP=1` to delete per-task JSON tickets once all tasks are `completed`,
  mimicking the "ephemeral control-plane state" behavior observed in Claude Code.

## Scheduling (Round-Based)

A "round" is one fanout barrier (typically one `multi_task` call).

A task is runnable when:

- `status == "pending"`
- `owner` is empty/unset
- all referenced `blocked_by` tasks are `completed`

Minimal state transitions:

- `pending` -> `in_progress` (manager assigns `owner`, schedules execution)
- `in_progress` -> `completed` (worker succeeded)
- `in_progress` -> `failed` (worker failed)

## Map-Reduce

Map-reduce is expressed in the task graph:

- `MAP`: multiple independent tasks in the same round (fanout N)
- `REDUCE`: one task that depends on all map tasks (fanout 1)

## Artifacts

Artifacts are the source of truth for "full context"; summaries are compact carry-forward signals.

Suggested layout:

```
tasks.md
.ouro_artifacts/orchestrations/<run_id>/
  tasks.snapshot.md
  round_0/
    task_T0.md
    task_T1.md
```

Downstream steps should prefer `summary`, and open full artifacts on demand.

## Why Fanout-Only `multi_task`

Claude Code Tasks separates "task graph state" (dependencies, readiness, ownership) from execution.
v1 adopts the same separation:

- `task_board` owns dependencies.
- `multi_task` is only for acceleration: N independent ReAct workers, no internal DAG.

This reduces tool-call overhead and makes failure modes easier to diagnose.

## Parallel Writes (Optional): Lazy Worktree Isolation

If workers are allowed to write/edit/run arbitrary commands in a shared workspace, concurrency is non-deterministic.
A pragmatic compromise is **write-on-demand worktree isolation**:

- Workers start in the main workspace for read-only exploration.
- When a worker decides it must write, it first creates/acquires a dedicated git worktree and writes there.
- The worker reports back `WORKTREE_PATH + diff/commit` for the manager to merge.

Even with "all nodes are full ReAct", we still need small hard budgets (`max_parallel`, per-worker timeouts).

## Cleanup

v1 treats tasks as a control-plane artifact. Completed tasks can be kept for auditability, but the
runtime SHOULD offer a simple cleanup policy (manual or time-based) to prevent state accumulation.

## References (External)

- ClaudeLog: "What are Tasks in Claude Code?" (2026-01-22)
- Rick Hightower: "Claude Code Todos to Tasks" (2026-01-26)
- Community notes on on-disk storage and cleanup behavior for `~/.claude/tasks`
