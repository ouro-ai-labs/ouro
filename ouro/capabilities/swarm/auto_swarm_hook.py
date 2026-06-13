"""AutoSwarmHook — automatically decomposes complex tasks and runs them via SwarmCoordinator."""

from __future__ import annotations

from ouro.capabilities.swarm.analyzer import TaskAnalyzer
from ouro.capabilities.swarm.coordinator import SwarmCoordinator
from ouro.capabilities.tasks.store import TaskStore
from ouro.core.llm import LLMMessage
from ouro.core.log import get_logger
from ouro.core.loop import ProgressEvent

logger = get_logger(__name__)


class AutoSwarmHook:
    """Hook that automatically enables swarm mode for complex tasks."""

    def __init__(
        self,
        llm,
        builder_factory,
        complexity_threshold: float = 0.6,
        max_agents: int = 3,
        enabled: bool = True,
    ):
        self.llm = llm
        self.builder_factory = builder_factory
        self.analyzer = TaskAnalyzer(llm, complexity_threshold)
        self.max_agents = max_agents
        self.enabled = enabled
        self._swarm_result: str | None = None

    async def on_run_start(self, ctx, messages) -> None:
        """Intercept run start and potentially switch to swarm mode."""
        if not self.enabled:
            return

        task = getattr(ctx, "task", "")
        if not task:
            return

        logger.info(f"AutoSwarm: Analyzing task complexity: {task[:100]}...")
        ctx.progress.emit(
            ProgressEvent(
                kind="info",
                payload={"message": "Analyzing task complexity for possible swarm execution..."},
            )
        )
        analysis = await self.analyzer.analyze(task)

        logger.info(
            f"AutoSwarm: complexity={analysis.complexity_score:.2f}, "
            f"decompose={analysis.should_decompose}"
        )

        if not self.analyzer.should_use_swarm(analysis):
            logger.info("AutoSwarm: Task is simple enough for single-agent execution")
            return

        subtasks = analysis.subtasks or []
        ctx.progress.emit(
            ProgressEvent(
                kind="swarm_header",
                payload={
                    "line": f"Swarm selected: complexity={analysis.complexity_score:.2f}, subtasks={len(subtasks)}",
                    "title": "Swarm",
                },
            )
        )
        logger.info(f"AutoSwarm: Decomposing into {len(subtasks)} subtasks")

        import tempfile
        from pathlib import Path

        db_path = Path(tempfile.gettempdir()) / f"ouro-swarm-{id(task)}.db"
        store = TaskStore(str(db_path))

        ctx.progress.emit(ProgressEvent(kind="swarm_reset", payload={"keep_headers": True}))
        for idx, subtask in enumerate(subtasks, start=1):
            ctx.progress.emit(
                ProgressEvent(
                    kind="swarm_plan_item",
                    payload={"line": f"#{idx} {subtask['subject']}", "title": "Swarm Plan"},
                )
            )
            store.create(
                subject=subtask["subject"],
                description=subtask["description"],
                activeForm=subtask.get("activeForm"),
            )

        coordinator = SwarmCoordinator(
            store,
            self.builder_factory,
            heartbeat_interval=5.0,
            progress=ctx.progress,
        )

        num_agents = min(len(subtasks), self.max_agents)
        await coordinator.spawn_agents(n=num_agents)

        ctx.progress.emit(
            ProgressEvent(
                kind="swarm_header",
                payload={"line": f"Starting swarm with {num_agents} agent(s)...", "title": "Swarm"},
            )
        )
        logger.info(f"AutoSwarm: Running {num_agents} agents...")
        await coordinator.run_until_done()

        status = coordinator.get_status()
        tasks = store.list_all()

        ctx.progress.emit(
            ProgressEvent(
                kind="swarm_status",
                payload={
                    "line": "Swarm complete: "
                    f"{status.completed}/{status.total_tasks} tasks done, "
                    f"{status.in_progress} running, {status.blocked} blocked",
                    "title": "Swarm Result",
                },
            )
        )

        result_parts = [
            "# Swarm Execution Complete\n",
            f"**Task:** {task}\n",
            f"**Complexity:** {analysis.complexity_score:.2f}\n",
            f"**Subtasks:** {status.total_tasks} total, {status.completed} completed\n\n",
        ]

        for t in tasks:
            result_parts.append(f"## {t.subject}\n")
            result_parts.append(f"Status: {t.status.value}\n")
            result_parts.append(f"Description: {t.description}\n\n")

        self._swarm_result = "\n".join(result_parts)

        messages.append(
            LLMMessage(
                role="system",
                content=f"[SWARM RESULT] {self._swarm_result}",
            )
        )

        logger.info("AutoSwarm: Swarm execution complete")

    def get_swarm_result(self) -> str | None:
        """Return the last swarm execution result."""
        return self._swarm_result
