"""Orchestration examples that used to stress the old DAG implementation.

These tests validate the new model:
- dependencies live in task_board
- execution fanout is done by multi_task (no internal DAG)
- orchestration proceeds in rounds (barriers)
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from orchestration.v1 import RoundOrchestratorV1
from tools.multi_task import MultiTaskExecution, TaskExecutionResult
from tools.task_board import TaskBoardTool


@dataclass
class FakeMultiTask:
    round_to_results: list[dict[int, TaskExecutionResult]]
    calls: int = 0
    last_tasks: list[str] | None = None

    async def execute_structured(self, *, tasks, max_parallel, artifact_root, cleanup):
        _ = (max_parallel, artifact_root, cleanup)
        self.last_tasks = list(tasks)
        results_for_round = self.round_to_results[self.calls]
        self.calls += 1
        return MultiTaskExecution(
            tasks=list(tasks),
            results=results_for_round,
            artifact_root=artifact_root,
            dag_path=str(artifact_root / "dag.mmd"),
            violations=None,
        )


def _ok(idx: int, *, summary: str) -> TaskExecutionResult:
    return TaskExecutionResult(
        status="success",
        output=f"out-{idx}",
        summary=summary,
        key_findings="- k",
        errors="- none",
        artifact_path=f"/tmp/artifact-{idx}.md",
    )


@pytest.mark.asyncio
async def test_example_independent_fanout_one_round(tmp_path):
    """Example 1: analyze N repos in parallel (no dependencies)."""
    board = TaskBoardTool()
    tasks_path = tmp_path / "tasks.md"
    await board.execute(operation="hydrate", path=str(tasks_path), goal="Compare repos")

    t0 = json.loads(
        await board.execute(
            operation="create",
            path=str(tasks_path),
            subject="Repo A",
            description="Summarize repo A",
        )
    )["id"]
    t1 = json.loads(
        await board.execute(
            operation="create",
            path=str(tasks_path),
            subject="Repo B",
            description="Summarize repo B",
        )
    )["id"]
    t2 = json.loads(
        await board.execute(
            operation="create",
            path=str(tasks_path),
            subject="Repo C",
            description="Summarize repo C",
        )
    )["id"]

    fake = FakeMultiTask(
        round_to_results=[{0: _ok(0, summary="A"), 1: _ok(1, summary="B"), 2: _ok(2, summary="C")}]
    )
    orch = RoundOrchestratorV1(
        task_board=board,
        multi_task=fake,
        tasks_path=str(tasks_path),
        artifact_root=str(tmp_path / "artifacts"),
    )
    run = await orch.run(max_rounds=10, cleanup_artifacts=False)

    assert run.deadlocked is False
    assert set(run.completed) == {t0, t1, t2}
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_example_two_stage_dependency_two_rounds(tmp_path):
    """Example 2: flights -> itinerary (dependency)."""
    board = TaskBoardTool()
    tasks_path = tmp_path / "tasks.md"
    await board.execute(operation="hydrate", path=str(tasks_path), goal="Plan trip")

    flights = json.loads(
        await board.execute(
            operation="create",
            path=str(tasks_path),
            subject="Find flights",
            description="Find best flights in date range",
        )
    )["id"]
    itinerary = json.loads(
        await board.execute(
            operation="create",
            path=str(tasks_path),
            subject="Create itinerary",
            description="Build itinerary using chosen flight",
            blocked_by=[flights],
        )
    )["id"]

    fake = FakeMultiTask(
        round_to_results=[{0: _ok(0, summary="flights found")}, {0: _ok(0, summary="itinerary")}]
    )
    orch = RoundOrchestratorV1(
        task_board=board,
        multi_task=fake,
        tasks_path=str(tasks_path),
        artifact_root=str(tmp_path / "artifacts"),
    )
    run = await orch.run(max_rounds=10, cleanup_artifacts=False)

    assert run.deadlocked is False
    assert run.failed == []
    assert fake.calls == 2
    assert set(run.completed) == {flights, itinerary}


@pytest.mark.asyncio
async def test_example_dynamic_fanout_requires_multiple_runs(tmp_path):
    """Example 3: PDF ingest decides how many chapter workers to spawn.

    The key point: the full fanout size is unknown at the start.
    With the new model, the manager can do:
    - Run 1 round to ingest/extract headings
    - Create chapter tasks based on that output
    - Run again to execute the derived fanout + reduce

    This avoids requiring the initial plan to contain the full DAG.
    """
    board = TaskBoardTool()
    tasks_path = tmp_path / "tasks.md"
    await board.execute(operation="hydrate", path=str(tasks_path), goal="Summarize pdf")

    ingest = json.loads(
        await board.execute(
            operation="create",
            path=str(tasks_path),
            subject="Ingest PDF",
            description="Extract up to 3 headings from the pdf",
        )
    )["id"]

    fake1 = FakeMultiTask(round_to_results=[{0: _ok(0, summary="H1,H2,H3")}])
    orch1 = RoundOrchestratorV1(
        task_board=board,
        multi_task=fake1,
        tasks_path=str(tasks_path),
        artifact_root=str(tmp_path / "artifacts1"),
    )
    run1 = await orch1.run(max_rounds=1, cleanup_artifacts=False)
    assert set(run1.completed) == {ingest}
    assert fake1.calls == 1

    # Manager creates derived fanout tasks.
    h1 = json.loads(
        await board.execute(
            operation="create",
            path=str(tasks_path),
            subject="Summarize H1",
            description="Summarize heading H1",
            blocked_by=[ingest],
        )
    )["id"]
    h2 = json.loads(
        await board.execute(
            operation="create",
            path=str(tasks_path),
            subject="Summarize H2",
            description="Summarize heading H2",
            blocked_by=[ingest],
        )
    )["id"]
    h3 = json.loads(
        await board.execute(
            operation="create",
            path=str(tasks_path),
            subject="Summarize H3",
            description="Summarize heading H3",
            blocked_by=[ingest],
        )
    )["id"]
    reduce_task = json.loads(
        await board.execute(
            operation="create",
            path=str(tasks_path),
            subject="Reduce",
            description="Merge chapter summaries into final",
            blocked_by=[h1, h2, h3],
        )
    )["id"]

    fake2 = FakeMultiTask(
        round_to_results=[
            {0: _ok(0, summary="S1"), 1: _ok(1, summary="S2"), 2: _ok(2, summary="S3")},
            {0: _ok(0, summary="FINAL")},
        ]
    )
    orch2 = RoundOrchestratorV1(
        task_board=board,
        multi_task=fake2,
        tasks_path=str(tasks_path),
        artifact_root=str(tmp_path / "artifacts2"),
    )
    run2 = await orch2.run(max_rounds=10, cleanup_artifacts=False)

    assert run2.deadlocked is False
    assert fake2.calls == 2
    assert set(run2.completed) >= {h1, h2, h3, reduce_task}
