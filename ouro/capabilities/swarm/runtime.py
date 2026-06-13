"""Swarm runtime facade over the scheduler implementation."""

from __future__ import annotations

from ouro.capabilities.swarm.coordinator import SwarmCoordinator


class SwarmRuntime:
    """Execute a Task V2 plan using the existing scheduler implementation."""

    def __init__(self, coordinator: SwarmCoordinator) -> None:
        self.coordinator = coordinator

    async def run_until_done(self, *, store, plan, root_task: str) -> None:
        # The first slice delegates execution to the existing coordinator.
        # Planner output is already persisted in the shared task store.
        del plan, root_task
        self.coordinator.store = store
        self.coordinator.engine.store = store
        await self.coordinator.run_until_done()
