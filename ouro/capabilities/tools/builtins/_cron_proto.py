"""Capability-local Protocol for the CronScheduler dependency.

`cron_tool` historically TYPE_CHECKING-imported `bot.proactive.CronScheduler`,
which violates the layer boundary (capabilities → interfaces). This file
defines the structural surface cron_tool needs; the real `CronScheduler`
in `ouro.interfaces.bot.proactive` automatically satisfies it.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CronScheduler(Protocol):
    """Minimal surface required by `CronTool`. The real implementation
    lives in the bot interface and registers itself at startup."""

    @property
    def jobs(self) -> list[Any]: ...

    def add_job(
        self,
        schedule: str,
        prompt: str,
        *,
        name: str = "",
        session_mode: str = "main",
    ) -> Any: ...

    def remove_job(self, job_id: str) -> bool: ...
