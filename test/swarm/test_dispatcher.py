"""Tests for SwarmExecutionDispatcher."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ouro.capabilities.swarm.analyzer import TaskAnalysis
from ouro.capabilities.swarm.dispatcher import SwarmExecutionDispatcher
from ouro.capabilities.swarm.planner import PlannedTask, TaskPlan
from ouro.capabilities.swarm.synthesizer import TaskGraphSynthesizer
from ouro.capabilities.tasks.store import TaskStore


class StubAnalyzer:
    def __init__(self, should_use_swarm: bool):
        self._should_use_swarm = should_use_swarm

    async def analyze(self, task: str) -> TaskAnalysis:
        return TaskAnalysis(
            should_use_swarm=self._should_use_swarm,
            complexity_score=0.9 if self._should_use_swarm else 0.1,
            reasoning="stub",
        )

    def should_use_swarm(self, analysis: TaskAnalysis) -> bool:
        return analysis.should_use_swarm


class StubPlanner:
    async def plan(self, task: str) -> TaskPlan:
        return TaskPlan(
            summary=task,
            tasks=[
                PlannedTask(
                    local_id="inspect",
                    subject="Inspect",
                    description="Inspect current implementation",
                ),
                PlannedTask(
                    local_id="implement",
                    subject="Implement",
                    description="Implement after inspection",
                    blockedBy=["inspect"],
                ),
            ],
        )


class StubRuntime:
    def __init__(self):
        self.calls = 0

    async def run_until_done(self, *, store, plan, root_task: str) -> None:
        self.calls += 1
        for index, task in enumerate(store.list_all(), start=1):
            store.update(
                task.id,
                status="completed",
                metadata={"result": f"result-{index}", "worker_agent_id": f"agent-{index}"},
            )


class TestSwarmExecutionDispatcher:
    async def test_simple_task_uses_single_agent_runner(self) -> None:
        runtime = StubRuntime()
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "tasks.db"
            dispatcher = SwarmExecutionDispatcher(
                analyzer=StubAnalyzer(False),
                planner=StubPlanner(),
                store_factory=lambda: TaskStore(store_path),
                runtime=runtime,
                synthesizer=TaskGraphSynthesizer(),
                single_agent_runner=_single_agent_runner,
            )

            result = await dispatcher.run("Simple task")

        assert result == "single-agent: Simple task"
        assert runtime.calls == 0
        assert dispatcher.last_decision is not None
        assert dispatcher.last_decision.used_swarm is False

    async def test_complex_task_uses_swarm_path_and_persists_dependencies(self) -> None:
        runtime = StubRuntime()
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "tasks.db"
            store_ref: dict[str, TaskStore] = {}

            def make_store() -> TaskStore:
                store = TaskStore(store_path)
                store_ref["store"] = store
                return store

            dispatcher = SwarmExecutionDispatcher(
                analyzer=StubAnalyzer(True),
                planner=StubPlanner(),
                store_factory=make_store,
                runtime=runtime,
                synthesizer=TaskGraphSynthesizer(),
                single_agent_runner=_single_agent_runner,
            )

            result = await dispatcher.run("Complex task")
            tasks = store_ref["store"].list_all()

        assert runtime.calls == 1
        assert len(tasks) == 2
        assert tasks[1].blockedBy == [tasks[0].id]
        assert tasks[0].metadata["result"] == "result-1"
        assert "Completed task-graph execution for: Complex task" in result
        assert "Result: result-1" in result
        assert dispatcher.last_decision is not None
        assert dispatcher.last_decision.used_swarm is True


async def _single_agent_runner(task: str) -> str:
    return f"single-agent: {task}"
