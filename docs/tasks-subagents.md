# Tasks + sub-agents architecture (experimental)

This document describes the **current** Tasks orchestration flow in ouro.

Status:

- Tasks + `sub_agent_batch` are **experimental**.
- Legacy `multi_task` remains available and is not removed.

## Design goals

- Keep a single in-memory task graph (`TaskStore`) as the source of truth.
- Let the LLM orchestrate via tool calls (not hardcoded scheduler rules).
- Support dependency-aware fanout/join with parallel worker execution.
- Keep output debuggable (`TaskList`, `tasksMd`, optional `TaskDumpMd`).

## Core components

- `TaskStore` (`agent/tasks.py`)
  - Stores task nodes (`id/content/activeForm/status/blockedBy/detail`).
  - Computes reverse edges and `available` set.
  - Enforces dependency gates (`TaskBlockedError`) and dependency mutation freeze for non-`pending` tasks.
- Task graph tools (`tools/task_tools.py`)
  - `TaskCreate` / `TaskUpdate` / `TaskList` / `TaskGet` / `TaskGetMany`
  - `TaskFanout` for leaf fanout + optional join dependency rewrite
  - `TaskDumpMd` for optional on-disk snapshot
- `sub_agent_batch` (`tools/sub_agent_batch.py`)
  - Runs fresh ReAct workers in parallel.
  - Reads upstream dependency outputs from `TaskStore`.
  - Writes successful worker output back to `TaskStore` (`status=completed`, `detail=output`) best-effort.
  - Also returns a replayable `updates` array for explicit `TaskUpdate(updates=[...])`.
- `TaskPolicy` (`agent/task_policy.py`)
  - Runtime policies in the main loop:
    - enforce incomplete-task continuation before final answer
    - prefer terminal join task detail as final output when graph is complete
    - optional final `TaskDumpMd` auto-run when user explicitly requested it

## End-to-end flow (prompt -> task graph -> final output)

1. User prompt enters `LoopAgent.run`.
2. LLM builds/updates the graph through Task tools:
   - `TaskCreate` creates tasks
   - `TaskUpdate` sets status/edges/detail
   - `TaskFanout` expands N children and rewrites join `blockedBy` when needed
3. LLM calls `TaskList` to read:
   - current DAG state
   - `available` task IDs (ready to execute)
4. For parallel leaf tasks, LLM calls `sub_agent_batch` with selected `taskId`s.
5. Each sub-agent executes one task with:
   - simplified conversation context
   - direct upstream task details (`blockedBy` completed outputs)
6. `sub_agent_batch` writes worker outputs into `TaskStore.detail` and marks completed (best effort), then returns structured results.
7. Main LLM continues graph progression until downstream join tasks are unblocked and completed.
8. `TaskPolicy` blocks premature finalization when tasks are incomplete, then picks terminal join detail as final answer when available.
9. If user asked for `TaskDumpMd(path=..., includeDebug=...)`, `TaskPolicy` performs a final snapshot write at the end.

## Important behavior constraints

- Dependency edit constraints:
  - `blockedBy`/`addBlockedBy`/`removeBlockedBy`/`addBlocks`/`removeBlocks` are only editable while task is `pending`.
- Status gate constraints:
  - Transition to `in_progress`/`completed` is rejected if unresolved dependencies remain.
- Detail handling:
  - `TaskUpdate` uses append-only semantics by default.
  - `replaceDetail=true` explicitly overwrites existing detail.

## Debug surfaces

- `TaskList` response includes:
  - normalized task list
  - `available` IDs
  - rendered `tasksMd` + `debugTasksMd`
- `TaskDumpMd(path, includeDebug)` writes a stable snapshot for offline inspection.

## Current non-goals

- Cross-session persistence/hydration.
- Distributed task claiming/leases.
- Automatic conflict resolution for concurrent code edits.
