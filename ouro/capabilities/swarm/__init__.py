"""Agent Swarm — multi-agent task coordination.

Phase 2 introduces a SwarmCoordinator that manages a pool of agents
working from a shared TaskStore. Agents claim tasks atomically, work
on them, and mark them complete. The coordinator handles agent lifecycle
(task assignment, health checks, recovery) and provides a unified
interface for swarm operations.
"""

from .coordinator import SwarmCoordinator

__all__ = ["SwarmCoordinator"]
