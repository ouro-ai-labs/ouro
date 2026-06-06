"""SwarmCoordinator — multi-agent task coordination.

Manages a pool of agents working from a shared TaskStore. Each agent
claims tasks atomically, works on them via the core loop, and marks
them complete. The coordinator handles:

- Agent lifecycle (spawn, health check, recovery)
- Task assignment (claim → work → complete)
- Swarm-level queries (progress, bottlenecks, available agents)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ouro.capabilities.tasks.engine import TaskEngine
from ouro.capabilities.tasks.models import TaskStatus
from ouro.capabilities.tasks.store import TaskStore
from ouro.core.log import get_logger
from ouro.core.loop import NullProgressSink

if TYPE_CHECKING:
    from ouro.capabilities.builder import ComposedAgent

logger = get_logger(__name__)


@dataclass
class AgentHandle:
    """Reference to a running agent in the swarm."""

    agent_id: str
    agent: ComposedAgent
    task_ids: list[str] = field(default_factory=list)
    last_heartbeat: float = field(default_factory=time.time)
    total_tasks_completed: int = 0
    total_tasks_failed: int = 0


@dataclass
class SwarmStatus:
    """Snapshot of swarm state."""

    agents: list[AgentHandle]
    total_tasks: int
    pending: int
    in_progress: int
    completed: int
    blocked: int
    available_agents: list[str]


class SwarmCoordinator:
    """Coordinate multiple agents working from a shared task store.

    Usage:
        coordinator = SwarmCoordinator(store, builder_factory)
        await coordinator.spawn_agents(n=3)  # Create 3 agents
        await coordinator.run_until_done()   # Block until all tasks complete
    """

    def __init__(
        self,
        store: TaskStore,
        builder_factory,
        heartbeat_interval: float = 30.0,
        max_idle_iterations: int = 10,
        progress=None,
    ) -> None:
        self.store = store
        self.engine = TaskEngine(store)
        self.builder_factory = builder_factory
        self.agents: dict[str, AgentHandle] = {}
        self.heartbeat_interval = heartbeat_interval
        self.max_idle_iterations = max_idle_iterations
        self.progress = progress or NullProgressSink()
        self._shutdown = False

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    async def spawn_agents(self, n: int = 1) -> list[str]:
        """Spawn n agents and return their IDs."""
        ids: list[str] = []
        for i in range(n):
            agent_id = f"agent-{len(self.agents) + i + 1}"
            builder = self.builder_factory(agent_id)
            agent = builder.build()
            handle = AgentHandle(agent_id=agent_id, agent=agent)
            self.agents[agent_id] = handle
            ids.append(agent_id)
            logger.info(f"Spawned agent {agent_id}")
            self.progress.event("swarm_agent", {"agent": agent_id, "title": "Swarm"})
        return ids

    async def remove_agent(self, agent_id: str) -> bool:
        """Remove an agent and unassign its tasks."""
        handle = self.agents.pop(agent_id, None)
        if not handle:
            return False
        for task_id in handle.task_ids:
            self.store.unassign(task_id)
        logger.info(f"Removed agent {agent_id}, unassigned {len(handle.task_ids)} tasks")
        return True

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run_until_done(self) -> None:
        """Run the swarm until all tasks are completed or failed."""
        idle_count = 0
        while not self._shutdown:
            status = self.get_status()
            self.progress.event(
                "swarm_status",
                {
                    "line": "Swarm status: "
                    f"{status.completed}/{status.total_tasks} done, "
                    f"{status.in_progress} running, "
                    f"{status.blocked} blocked, "
                    f"{status.pending} pending",
                    "title": "Swarm Status",
                },
            )
            if status.pending == 0 and status.in_progress == 0:
                idle_count += 1
                if idle_count >= self.max_idle_iterations:
                    logger.info("Swarm idle — all tasks resolved")
                    break
            else:
                idle_count = 0

            # Try to assign available tasks to idle agents
            await self._assign_tasks()

            # Health check
            await self._health_check()

            await asyncio.sleep(min(self.heartbeat_interval, 1.0))

    async def _assign_tasks(self) -> None:
        """Claim and execute available tasks for idle agents."""
        available = self.store.list_available()
        if not available:
            return

        for handle in self.agents.values():
            if handle.task_ids:  # Agent is busy
                continue
            if not available:
                break

            task = available.pop(0)
            result = self.store.claim(task.id, handle.agent_id)
            if result.success:
                handle.task_ids.append(task.id)
                handle.last_heartbeat = time.time()
                self.progress.event(
                    "swarm_assignment",
                    {
                        "agent": handle.agent_id,
                        "assignment": f"task #{task.id}: {task.activeForm or task.subject}",
                        "title": "Swarm",
                    },
                )
                # Fire-and-forget task execution
                asyncio.create_task(
                    self._run_task(handle, task.id),
                    name=f"swarm-task-{task.id}",
                )

    async def _run_task(self, handle: AgentHandle, task_id: str) -> None:
        """Execute a single task and mark it complete."""
        task = self.store.get(task_id)
        if not task:
            return

        try:
            self.progress.event(
                "swarm_assignment",
                {
                    "agent": handle.agent_id,
                    "assignment": f"task #{task_id}: {task.activeForm or task.subject}",
                    "title": "Swarm",
                },
            )
            # Build the task prompt
            prompt = self._build_task_prompt(task)

            # Run the agent
            await handle.agent.run(prompt)

            # Mark complete
            self.engine.complete_task(task_id)
            handle.total_tasks_completed += 1
            logger.info(f"Agent {handle.agent_id} completed task {task_id}")
            self.progress.event(
                "swarm_assignment",
                {
                    "agent": handle.agent_id,
                    "assignment": f"completed #{task_id}: {task.subject}",
                    "title": "Swarm",
                },
            )

        except Exception as e:
            logger.error(f"Agent {handle.agent_id} failed task {task_id}: {e}")
            handle.total_tasks_failed += 1
            self.progress.event(
                "swarm_assignment",
                {
                    "agent": handle.agent_id,
                    "assignment": f"failed #{task_id}; returning it to the queue",
                    "title": "Swarm",
                },
            )
            # Unassign so another agent can try
            self.store.unassign(task_id)

        finally:
            handle.task_ids.remove(task_id)
            handle.last_heartbeat = time.time()

    def _build_task_prompt(self, task) -> str:
        """Build a prompt for the agent to execute a task."""
        lines = [
            f"Task: {task.subject}",
            f"Description: {task.description}",
        ]
        if task.activeForm:
            lines.append(f"Active Form: {task.activeForm}")
        if task.metadata:
            lines.append(f"Metadata: {task.metadata}")
        lines.append("\nExecute this task and report results.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def _health_check(self) -> None:
        """Check agent health and recover stale agents."""
        now = time.time()
        stale_threshold = self.heartbeat_interval * 3

        for handle in list(self.agents.values()):
            if now - handle.last_heartbeat > stale_threshold:
                logger.warning(f"Agent {handle.agent_id} stale — recovering tasks")
                for task_id in list(handle.task_ids):
                    self.store.unassign(task_id)
                    handle.task_ids.remove(task_id)
                handle.last_heartbeat = now

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_status(self) -> SwarmStatus:
        """Return current swarm status."""
        all_tasks = self.store.list_all()
        completed_ids = {t.id for t in all_tasks if t.status == TaskStatus.COMPLETED}

        pending = sum(1 for t in all_tasks if t.status == TaskStatus.PENDING)
        in_progress = sum(1 for t in all_tasks if t.status == TaskStatus.IN_PROGRESS)
        completed = len(completed_ids)
        blocked = sum(
            1 for t in all_tasks if t.blockedBy and not all(b in completed_ids for b in t.blockedBy)
        )

        available = [h.agent_id for h in self.agents.values() if not h.task_ids]

        return SwarmStatus(
            agents=list(self.agents.values()),
            total_tasks=len(all_tasks),
            pending=pending,
            in_progress=in_progress,
            completed=completed,
            blocked=blocked,
            available_agents=available,
        )

    def shutdown(self) -> None:
        """Signal the swarm to shut down gracefully."""
        self._shutdown = True
        logger.info("Swarm shutdown requested")
