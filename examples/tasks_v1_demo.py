"""Demo: Claude-like tasks (v1) with task_board + round-based fanout orchestration.

This script is intentionally deterministic (no real LLM calls). It exists to validate the
end-to-end control-plane flow:
  prompt -> tasks -> runnable -> fanout -> update -> repeat

Run:
  python3 examples/tasks_v1_demo.py
  python3 examples/tasks_v1_demo.py --store dir
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Add repo root to sys.path so this file can be run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestration.v1 import RoundOrchestratorV1
from tools.multi_task import MultiTaskExecution, TaskExecutionResult
from tools.task_board import TaskBoardTool


@dataclass
class FakeMultiTask:
    """Deterministic multi_task replacement (no sub-agents).

    Each multi_task call consumes one entry from round_to_results.
    """

    round_to_results: list[dict[int, TaskExecutionResult]]
    calls: int = 0

    async def execute_structured(self, *, tasks, max_parallel, artifact_root, cleanup):
        _ = (tasks, max_parallel, artifact_root, cleanup)
        results_for_round = self.round_to_results[self.calls]
        self.calls += 1
        return MultiTaskExecution(
            tasks=list(tasks),
            results=results_for_round,
            artifact_root=artifact_root,
            dag_path=str(artifact_root / "dag.mmd"),
            violations=None,
        )


def _ok(idx: int, *, summary: str, artifact_root: Path) -> TaskExecutionResult:
    return TaskExecutionResult(
        status="success",
        output=f"out-{idx}",
        summary=summary,
        key_findings="- (demo)",
        errors="- none",
        artifact_path=str(artifact_root / f"fake_artifact_{idx}.md"),
    )


async def _print_board_snapshot(
    board: TaskBoardTool, *, path: str, store: str, task_list_id: str | None
) -> None:
    raw = await board.execute(
        operation="list",
        path=path,
        store=store,
        task_list_id=task_list_id,
        limit=200,
    )
    obj = json.loads(raw)
    print("\nTASK_BOARD SNAPSHOT")
    print(f"goal: {obj.get('goal')}")
    for t in obj.get("tasks") or []:
        tid = t.get("id")
        status = t.get("status")
        bby = t.get("blocked_by") or []
        subj = t.get("subject") or ""
        print(f"- {tid}: {status} blocked_by={bby} subject={subj!r}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", choices=["markdown", "dir"], default="markdown")
    ap.add_argument("--path", default="")
    ap.add_argument("--task-list-id", default="")
    args = ap.parse_args()

    # Keep everything contained for experimentation.
    workdir = Path(tempfile.mkdtemp(prefix="ouro_tasks_demo_"))
    artifacts_root = workdir / "artifacts"
    artifacts_root.mkdir(parents=True, exist_ok=True)

    store = args.store
    task_list_id = args.task_list_id.strip() or None

    if args.path.strip():
        tasks_path = args.path.strip()
    else:
        tasks_path = str(workdir / ("tasks.md" if store == "markdown" else "task_list"))

    board = TaskBoardTool()

    # Round 0: ingest (unknown fanout size at start).
    await board.execute(
        operation="hydrate",
        path=tasks_path,
        store=store,
        task_list_id=task_list_id,
        goal="Summarize a PDF by chapters (demo)",
    )
    ingest = json.loads(
        await board.execute(
            operation="create",
            path=tasks_path,
            store=store,
            task_list_id=task_list_id,
            subject="Ingest PDF",
            description="Extract up to 3 chapter headings from the PDF",
            active_form="Ingesting PDF",
        )
    )["id"]

    fake1 = FakeMultiTask(
        round_to_results=[{0: _ok(0, summary="H1,H2,H3", artifact_root=artifacts_root)}]
    )
    orch1 = RoundOrchestratorV1(
        task_board=board,
        multi_task=fake1,
        tasks_path=tasks_path,
        store=store,
        task_list_id=task_list_id,
        artifact_root=str(artifacts_root / "run1"),
    )
    run1 = await orch1.run(max_rounds=1, cleanup_artifacts=False, owner="demo")
    print(
        f"\nRUN1: rounds={run1.rounds} completed={run1.completed} failed={run1.failed} deadlocked={run1.deadlocked}"
    )
    await _print_board_snapshot(board, path=tasks_path, store=store, task_list_id=task_list_id)

    # Manager creates derived tasks based on ingest output.
    h1 = json.loads(
        await board.execute(
            operation="create",
            path=tasks_path,
            store=store,
            task_list_id=task_list_id,
            subject="Summarize H1",
            description="Summarize chapter H1",
            blocked_by=[ingest],
            active_form="Summarizing H1",
        )
    )["id"]
    h2 = json.loads(
        await board.execute(
            operation="create",
            path=tasks_path,
            store=store,
            task_list_id=task_list_id,
            subject="Summarize H2",
            description="Summarize chapter H2",
            blocked_by=[ingest],
            active_form="Summarizing H2",
        )
    )["id"]
    h3 = json.loads(
        await board.execute(
            operation="create",
            path=tasks_path,
            store=store,
            task_list_id=task_list_id,
            subject="Summarize H3",
            description="Summarize chapter H3",
            blocked_by=[ingest],
            active_form="Summarizing H3",
        )
    )["id"]
    reduce_task = json.loads(
        await board.execute(
            operation="create",
            path=tasks_path,
            store=store,
            task_list_id=task_list_id,
            subject="Reduce",
            description="Merge chapter summaries into final output",
            blocked_by=[h1, h2, h3],
            active_form="Reducing summaries",
        )
    )["id"]

    fake2 = FakeMultiTask(
        round_to_results=[
            {
                0: _ok(0, summary="S1", artifact_root=artifacts_root),
                1: _ok(1, summary="S2", artifact_root=artifacts_root),
                2: _ok(2, summary="S3", artifact_root=artifacts_root),
            },
            {0: _ok(0, summary="FINAL", artifact_root=artifacts_root)},
        ]
    )
    orch2 = RoundOrchestratorV1(
        task_board=board,
        multi_task=fake2,
        tasks_path=tasks_path,
        store=store,
        task_list_id=task_list_id,
        artifact_root=str(artifacts_root / "run2"),
    )
    run2 = await orch2.run(max_rounds=10, cleanup_artifacts=False, owner="demo")
    print(
        f"\nRUN2: rounds={run2.rounds} completed={run2.completed} failed={run2.failed} deadlocked={run2.deadlocked}"
    )
    await _print_board_snapshot(board, path=tasks_path, store=store, task_list_id=task_list_id)

    print("\nOUTPUT LOCATIONS")
    print(f"- workdir: {workdir}")
    if store == "markdown" and not task_list_id:
        print(f"- tasks.md: {tasks_path}")
    else:
        print(f"- task store: {tasks_path} (store={store}, task_list_id={task_list_id or 'none'})")
    print(f"- artifacts: {artifacts_root}")
    print(f"- ingest task id: {ingest}, reduce task id: {reduce_task}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
