"""Round-based orchestration (v1): Task Board + Fanout.

This is intentionally small and mechanical:
- `task_board` is the persistent plan/state.
- `multi_task` is pure fanout (independent subtasks only).

The manager loop (LLM) can use these primitives directly, but this module provides
an executable "runner" so we can unit test the scheduling semantics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.task_board import TaskBoardTool


@dataclass
class OrchestrationRun:
    rounds: int
    completed: list[str]
    failed: list[str]
    deadlocked: bool


def _render_worker_prompt(task: dict[str, Any], deps: list[dict[str, Any]]) -> str:
    subject = (task.get("subject") or "").strip()
    description = (task.get("description") or "").strip()

    dep_lines: list[str] = [f'- {d.get("id")}: {d.get("summary") or "(no summary)"}' for d in deps]

    parts = []
    if subject:
        parts.append(f"SUBJECT: {subject}")
    if description:
        parts.append(f"DESCRIPTION:\n{description}")
    if dep_lines:
        parts.append("DEPENDENCY_SUMMARIES:\n" + "\n".join(dep_lines))
    return "\n\n".join(parts).strip()


class RoundOrchestratorV1:
    """Execute a task graph by repeatedly running runnable tasks (fanout per round)."""

    def __init__(
        self,
        *,
        task_board: TaskBoardTool,
        multi_task: Any,
        tasks_path: str = "tasks.md",
        store: str = "markdown",
        task_list_id: str | None = None,
        artifact_root: str = ".ouro_artifacts/orchestrations",
    ) -> None:
        self.task_board = task_board
        self.multi_task = multi_task
        self.tasks_path = tasks_path
        self.store = store
        self.task_list_id = task_list_id
        self.artifact_root = Path(artifact_root)

    async def run(
        self,
        *,
        goal: str = "",
        max_rounds: int = 20,
        max_parallel: int = 4,
        cleanup_artifacts: bool | None = None,
        owner: str = "orchestrator_v1",
    ) -> OrchestrationRun:
        await self.task_board.execute(
            operation="hydrate",
            path=self.tasks_path,
            store=self.store,
            task_list_id=self.task_list_id,
            goal=goal,
        )

        completed: list[str] = []
        failed: list[str] = []
        deadlocked = False
        rounds_executed = 0

        for r in range(max_rounds):
            rounds_executed = r + 1
            runnable_raw = await self.task_board.execute(
                operation="runnable",
                path=self.tasks_path,
                store=self.store,
                task_list_id=self.task_list_id,
                limit=50,
            )
            runnable = json.loads(runnable_raw).get("runnable") or []
            runnable = [str(x).strip() for x in runnable if str(x).strip()]

            if not runnable:
                # Decide if we're done or deadlocked.
                all_raw = await self.task_board.execute(
                    operation="list",
                    path=self.tasks_path,
                    store=self.store,
                    task_list_id=self.task_list_id,
                    limit=200,
                )
                all_tasks = json.loads(all_raw).get("tasks") or []
                statuses = {t.get("id"): t.get("status") for t in all_tasks if isinstance(t, dict)}
                if statuses and all(v in {"completed", "failed"} for v in statuses.values()):
                    break
                deadlocked = True
                break

            # Mark in_progress up-front to avoid double-scheduling if the runner is re-entered.
            for tid in runnable:
                await self.task_board.execute(
                    operation="update",
                    path=self.tasks_path,
                    store=self.store,
                    task_list_id=self.task_list_id,
                    id=tid,
                    status="in_progress",
                    owner=owner,
                )

            prompts: list[str] = []
            for tid in runnable:
                t_raw = await self.task_board.execute(
                    operation="get",
                    path=self.tasks_path,
                    store=self.store,
                    task_list_id=self.task_list_id,
                    id=tid,
                )
                t = json.loads(t_raw)
                deps: list[dict[str, Any]] = []
                for dep_id in t.get("blocked_by") or []:
                    dep_raw = await self.task_board.execute(
                        operation="get",
                        path=self.tasks_path,
                        store=self.store,
                        task_list_id=self.task_list_id,
                        id=str(dep_id),
                    )
                    if dep_raw.startswith("Error:"):
                        continue
                    deps.append(json.loads(dep_raw))
                prompts.append(_render_worker_prompt(t, deps))

            round_dir = self.artifact_root / "run" / f"round_{r}"
            round_dir.mkdir(parents=True, exist_ok=True)

            exec_result = await self.multi_task.execute_structured(
                tasks=prompts,
                max_parallel=max_parallel,
                artifact_root=round_dir,
                cleanup=cleanup_artifacts,
            )
            # If multi_task rejected, mark all as failed and stop.
            if getattr(exec_result, "violations", None):
                for tid in runnable:
                    await self.task_board.execute(
                        operation="update",
                        path=self.tasks_path,
                        store=self.store,
                        task_list_id=self.task_list_id,
                        id=tid,
                        status="failed",
                        errors="; ".join(exec_result.violations or []),
                    )
                    failed.append(tid)
                break

            for idx, tid in enumerate(runnable):
                res = exec_result.results.get(idx)
                if res is None:
                    await self.task_board.execute(
                        operation="update",
                        path=self.tasks_path,
                        store=self.store,
                        task_list_id=self.task_list_id,
                        id=tid,
                        status="failed",
                        errors="missing result",
                    )
                    failed.append(tid)
                    continue

                status = "completed" if res.status == "success" else "failed"
                await self.task_board.execute(
                    operation="update",
                    path=self.tasks_path,
                    store=self.store,
                    task_list_id=self.task_list_id,
                    id=tid,
                    status=status,
                    summary=res.summary,
                    artifacts=[res.artifact_path, getattr(exec_result, "dag_path", "")],
                    errors=res.errors if status == "failed" else "",
                )
                (completed if status == "completed" else failed).append(tid)

        return OrchestrationRun(
            rounds=rounds_executed,
            completed=completed,
            failed=failed,
            deadlocked=deadlocked,
        )
