"""Deprecated auto-swarm hook.

Swarm execution is being moved out of the core loop hook lifecycle and
into an explicit dispatcher/runtime path built on Task V2. The hook is
kept only as a no-op compatibility shim during the transition.
"""

from __future__ import annotations

from ouro.core.log import get_logger

logger = get_logger(__name__)


class AutoSwarmHook:
    """Compatibility shim for the retired hook-based swarm path."""

    def __init__(
        self,
        llm,
        builder_factory,
        complexity_threshold: float = 0.6,
        max_agents: int = 3,
        enabled: bool = True,
    ):
        del llm, builder_factory, complexity_threshold, max_agents
        self.enabled = enabled
        self._warned = False

    async def on_run_start(self, ctx, messages) -> None:
        """Do nothing and warn once when the deprecated path is wired."""
        del ctx, messages
        if self.enabled and not self._warned:
            logger.warning(
                "AutoSwarmHook is deprecated and no longer executes swarm work. "
                "Use the Task V2-backed dispatcher/runtime path instead."
            )
            self._warned = True

    def get_swarm_result(self) -> str | None:
        """The deprecated hook path never produces a swarm result."""
        return None
