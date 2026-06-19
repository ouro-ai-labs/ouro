"""Tests for SwarmRuntime observability behavior."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ouro.capabilities.swarm.coordinator import SwarmCoordinator
from ouro.capabilities.swarm.runtime import SwarmRuntime
from ouro.capabilities.tasks.store import TaskStore
from ouro.core.loop import ProgressEvent


class RecordingProgress:
    def __init__(self):
        self.events: list[ProgressEvent] = []

    def emit(self, event: ProgressEvent) -> None:
        self.events.append(event)


class BuilderStub:
    def build(self):
        raise AssertionError("Worker build should not be needed in this test")


async def test_runtime_emits_status_only_on_change() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TaskStore(Path(tmpdir) / "tasks.db")
        store.create(subject="Task 1", description="...")
        progress = RecordingProgress()
        coordinator = SwarmCoordinator(store, lambda agent_id: BuilderStub(), progress=progress)
        runtime = SwarmRuntime(coordinator, default_agents=1)
        coordinator.agents["agent-1"] = (
            object()
        )  # prevent automatic spawn for this observability test
        coordinator._shutdown = True

        await runtime.run_until_done(store=store, plan=None, root_task="task")

    status_events = [event for event in progress.events if event.kind == "swarm_status"]
    assert len(status_events) <= 1


async def test_runtime_spawns_up_to_configured_default_agents() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TaskStore(Path(tmpdir) / "tasks.db")
        for i in range(7):
            store.create(subject=f"Task {i}", description="...")
        progress = RecordingProgress()
        spawn_calls: list[int] = []

        class BuildableStub:
            def build(self):
                return object()

        coordinator = SwarmCoordinator(store, lambda agent_id: BuildableStub(), progress=progress)

        original_spawn = coordinator.spawn_agents

        async def recording_spawn(n: int = 1):
            spawn_calls.append(n)
            return await original_spawn(n=n)

        coordinator.spawn_agents = recording_spawn  # type: ignore[method-assign]
        runtime = SwarmRuntime(coordinator, default_agents=5)
        coordinator._shutdown = True

        await runtime.run_until_done(store=store, plan=None, root_task="task")

    assert spawn_calls == [5]
