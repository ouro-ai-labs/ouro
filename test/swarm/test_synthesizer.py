"""Tests for TaskGraphSynthesizer."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ouro.capabilities.swarm.planner import PlannedTask, TaskPlan
from ouro.capabilities.swarm.synthesizer import TaskGraphSynthesizer
from ouro.capabilities.tasks.models import TaskStatus
from ouro.capabilities.tasks.store import TaskStore


async def test_synthesizer_includes_worker_results() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TaskStore(Path(tmpdir) / "tasks.db")
        first = store.create(subject="Inspect", description="Inspect code")
        second = store.create(subject="Implement", description="Implement fix")
        store.update(
            first.id,
            status=TaskStatus.COMPLETED,
            metadata={
                "worker_agent_id": "agent-1",
                "result": {
                    "summary": "Found the target module",
                    "artifacts": ["ouro/capabilities/swarm/analyzer.py"],
                },
            },
        )
        store.update(
            second.id,
            status=TaskStatus.COMPLETED,
            metadata={
                "worker_agent_id": "agent-2",
                "result": {"summary": "Applied the code change"},
            },
        )
        plan = TaskPlan(
            summary="Inspect then implement",
            tasks=[
                PlannedTask(local_id="inspect", subject="Inspect", description="Inspect code"),
                PlannedTask(local_id="implement", subject="Implement", description="Implement fix"),
            ],
        )

        result = await TaskGraphSynthesizer().summarize(
            task="Complex task",
            plan=plan,
            store=store,
        )

    assert "Task completion: 2/2 completed" in result
    assert "Result: Found the target module" in result
    assert "Artifacts: ouro/capabilities/swarm/analyzer.py" in result
    assert "Result: Applied the code change" in result
    assert "agent-1" in result
