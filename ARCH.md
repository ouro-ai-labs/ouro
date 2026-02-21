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

## End-to-End Flow (Manager Loop)

This section answers the practical questions: "is task_board a tool?", "how does it update tasks.md?",
"how is tasks.md constructed?", and "what is the full prompt -> plan -> execute -> update loop?"

### 1) Is `task_board` a tool?

Yes. `task_board` is a **tool** whose output is a persistent, machine-readable task graph.
It is not a second agent loop. The manager (main) ReAct loop uses it as a control-plane state store.

### 2) How to call `task_board` to record progress

The manager is responsible for recording progress. Sub-agents SHOULD NOT mutate the task board
to avoid multi-writer concurrency; they return summaries + artifact paths, and the manager writes them.

Typical calls (markdown store, persisting to `tasks.md`):

```json
{"operation":"hydrate","path":"tasks.md","goal":"Plan a trip to Osaka"}
```

```json
{"operation":"create","path":"tasks.md","subject":"Find flights","description":"Search GZ -> Osaka flights between 2026-02-20 and 2026-02-30. Return 3 options with prices.","active_form":"Finding flights"}
```

```json
{"operation":"create","path":"tasks.md","subject":"Build itinerary","description":"Create a 5-day itinerary using the chosen flight. Include day-by-day schedule.","blocked_by":["T0"],"active_form":"Building itinerary"}
```

```json
{"operation":"runnable","path":"tasks.md","limit":50}
```

```json
{"operation":"update","path":"tasks.md","id":"T0","status":"in_progress","owner":"round_0"}
```

```json
{"operation":"update","path":"tasks.md","id":"T0","status":"completed","summary":"Found 3 flight options. Cheapest is ...","artifacts":[".ouro_artifacts/20260221_.../task_0.md"],"errors":""}
```

Notes:
- `create/update/delete` do best-effort persistence. You can still call `sync` explicitly at fanout
  barriers for clarity.
- `status="deleted"` in `update` is a lifecycle shortcut that removes the task record.

### 3) How `tasks.md` is built

`tasks.md` is a deterministic, machine-written file with exactly one fenced JSON block.

Construction rules (markdown store):
- `hydrate` is idempotent. If `tasks.md` does not exist, it creates a new plan (with optional `goal`)
  and writes it immediately.
- `create/update/delete` mutate the in-memory plan and write a new `tasks.md` snapshot (best-effort).
- `sync` forces a write.

If you prefer `task.md` as a filename, use `path="task.md"`. The tool does not care about the name.

### 4) Full loop: prompt -> plan -> fanout -> update -> repeat

The loop is intentionally mechanical. Dependencies live in `task_board`, and parallelism is done via
`multi_task` fanout. There is no DAG compiler.

```mermaid
flowchart TD
  U["User prompt"] --> M["Manager ReAct loop (main agent)"]
  M -->|task_board.hydrate/create/update| S["Task store (tasks.md or task-list dir)"]
  M -->|task_board.runnable| R["Runnable task ids"]
  M -->|multi_task fanout (one round)| W["N worker ReAct loops"]
  W -->|summary + artifact path per task| M
  M -->|task_board.update (status/summary/artifacts/errors)| S
  M -->|repeat until done/deadlock| M
```

Round-based execution protocol:
1. `task_board.hydrate(goal=...)`
2. Planning step: create tasks + set `blocked_by` dependencies.
3. For each round:
   - `task_board.runnable()` to get runnable tasks.
   - If none:
     - If all tasks are terminal (`completed|failed`): stop (done).
     - Else: stop (deadlock), and either repair the graph (update deps) or split tasks further.
   - Mark runnable tasks `in_progress` + set `owner`.
   - Call `multi_task(tasks=[...])` once (fanout barrier).
   - For each result: `task_board.update(status, summary, artifacts, errors)`.
4. Optional: `task_board.sync()` at the end of each round or before exiting.

Dynamic fanout (unknown N at the start) is handled by multiple runs/rounds:
- Round 0: ingest (e.g., extract PDF headings).
- Manager creates derived tasks based on output.
- Next rounds: run the derived fanout, then a reduce task that depends on all fanout tasks.

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

- ClaudeLog: "What are Tasks in Claude Code?" (2026-01-22) https://claudelog.com/faqs/what-are-tasks-in-claude-code/
- Rick Hightower: "Claude Code Todos to Tasks" (2026-01-26) https://pub.spillwave.com/claude-code-todos-to-tasks-5a1b0e351a1c
- Community notes on on-disk storage and cleanup behavior for `~/.claude/tasks` (e.g., `.highwatermark`, `_groups.json`)
- Qiita: "Claude CodeのTask定義が「todo」から「task」へ変更されてたので調べてみた" (2026-01-25) https://qiita.com/yoshitake_1209/items/ae983de96a0f89b7d37b
