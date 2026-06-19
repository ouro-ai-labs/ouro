"""Swarm runtime facade over the scheduler implementation."""

from __future__ import annotations

import asyncio

from ouro.capabilities.swarm.coordinator import SwarmCoordinator
from ouro.capabilities.swarm.replanner import SwarmReplanner
from ouro.core.loop import ProgressEvent


class SwarmRuntime:
    """Execute a Task V2 plan using the existing scheduler implementation."""

    def __init__(
        self,
        coordinator: SwarmCoordinator,
        replanner: SwarmReplanner | None = None,
        default_agents: int = 5,
    ) -> None:
        self.coordinator = coordinator
        self.replanner = replanner or SwarmReplanner()
        self.default_agents = default_agents
        self._applied_followups: set[str] = set()
        self._last_status_line: str | None = None

    async def run_until_done(self, *, store, plan, root_task: str) -> None:
        # The runtime delegates scheduling to the existing coordinator and
        # opportunistically extends the task graph when completed tasks publish
        # structured follow-up tasks.
        del plan, root_task
        self.coordinator.store = store
        self.coordinator.engine.store = store

        if not self.coordinator.agents:
            await self.coordinator.spawn_agents(
                n=min(self.default_agents, max(1, len(store.list_all())))
            )

        idle_count = 0
        while not self.coordinator._shutdown:
            status = self.coordinator.get_status()
            status_line = (
                "Swarm status: "
                f"{status.completed}/{status.total_tasks} done, "
                f"{status.in_progress} running, "
                f"{status.blocked} blocked, "
                f"{status.pending} pending"
            )
            if status_line != self._last_status_line:
                self.coordinator.progress.emit(
                    ProgressEvent(
                        kind="swarm_status",
                        payload={"line": status_line, "title": "Swarm Status"},
                    )
                )
                self._last_status_line = status_line
            await self.coordinator._assign_tasks()
            await self.coordinator._reconcile_running_tasks()
            self._apply_followups(store)

            refreshed = self.coordinator.get_status()
            if refreshed.pending == 0 and refreshed.in_progress == 0:
                idle_count += 1
                if idle_count >= self.coordinator.max_idle_iterations:
                    break
            else:
                idle_count = 0

            await asyncio.sleep(min(self.coordinator.heartbeat_interval, 1.0))

    async def shutdown(self) -> None:
        """Cancel in-flight worker tasks and stop the coordinator."""
        await self.coordinator.shutdown()

    def _apply_followups(self, store) -> None:
        for task in store.list_all():
            if task.id in self._applied_followups:
                continue
            if task.metadata.get("result") and task.status.value == "completed":
                outcome = self.replanner.apply_followups(completed_task_id=task.id, store=store)
                if outcome.created_task_ids or isinstance(task.metadata.get("result"), dict):
                    self._applied_followups.add(task.id)
