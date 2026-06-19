"""Execution dispatcher for single-agent vs swarm task-graph runs."""

from __future__ import annotations

from dataclasses import dataclass

from ouro.capabilities.swarm.analyzer import TaskAnalysis, TaskAnalyzer
from ouro.capabilities.swarm.planner import TaskPlan, TaskPlanner
from ouro.capabilities.tasks.store import TaskStore
from ouro.core.loop import NullProgressSink, ProgressEvent


@dataclass
class DispatchDecision:
    """Observable routing decision for execution."""

    used_swarm: bool
    analysis: TaskAnalysis
    plan: TaskPlan | None = None


class SwarmExecutionDispatcher:
    """Choose single-agent execution or Task V2-backed swarm execution."""

    def __init__(
        self,
        *,
        analyzer: TaskAnalyzer,
        planner: TaskPlanner,
        store_factory,
        runtime,
        synthesizer,
        single_agent_runner,
        progress=None,
    ) -> None:
        self.analyzer = analyzer
        self.planner = planner
        self.store_factory = store_factory
        self.runtime = runtime
        self.synthesizer = synthesizer
        self.single_agent_runner = single_agent_runner
        self.progress = progress or NullProgressSink()
        self.last_decision: DispatchDecision | None = None

    async def run(self, task: str) -> str:
        analysis = await self.analyzer.analyze(task)
        if not self.analyzer.should_use_swarm(analysis):
            self.last_decision = DispatchDecision(used_swarm=False, analysis=analysis)
            return await self.single_agent_runner(task)

        plan = await self.planner.plan(task)
        self.progress.emit(
            ProgressEvent(
                kind="swarm_reset",
                payload={"keep_headers": False},
            )
        )
        self.progress.emit(
            ProgressEvent(
                kind="swarm_header",
                payload={
                    "line": f"Swarm selected: complexity={analysis.complexity_score:.2f}, tasks={len(plan.tasks)}",
                    "title": "Swarm",
                },
            )
        )
        for idx, planned in enumerate(plan.tasks, start=1):
            self.progress.emit(
                ProgressEvent(
                    kind="swarm_plan_item",
                    payload={
                        "line": f"#{idx} {planned.subject}",
                        "title": "Swarm Plan",
                    },
                )
            )
        store: TaskStore = self.store_factory()
        self._persist_plan(plan, store)
        await self.runtime.run_until_done(store=store, plan=plan, root_task=task)
        self.last_decision = DispatchDecision(used_swarm=True, analysis=analysis, plan=plan)
        return await self.synthesizer.summarize(task=task, plan=plan, store=store)

    def _persist_plan(self, plan: TaskPlan, store: TaskStore) -> dict[str, str]:
        id_map: dict[str, str] = {}
        for planned in plan.tasks:
            created = store.create(
                subject=planned.subject,
                description=planned.description,
                activeForm=planned.activeForm,
                metadata={**planned.metadata, "local_id": planned.local_id},
            )
            id_map[planned.local_id] = created.id

        for planned in plan.tasks:
            blocked_by = [id_map[dep] for dep in planned.blockedBy]
            if blocked_by:
                store.update(id_map[planned.local_id], blockedBy=blocked_by)
        return id_map
