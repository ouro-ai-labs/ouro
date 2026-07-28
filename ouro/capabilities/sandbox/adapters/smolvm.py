"""smol sandbox provider."""

from __future__ import annotations

import asyncio
from typing import Any

from ouro.core.sandbox import SandboxCapabilities, SandboxExecResult

from ..manager import SandboxProfile
from .base import ExecOnlySandboxSession, SandboxProviderError, normalize_exec_result, split_command


def _is_already_exists_error(error: Exception) -> bool:
    message = str(error).lower()
    return "already exists" in message or "already_exist" in message


class SmolVMSandboxSession(ExecOnlySandboxSession):
    """SDK-first smol session using the current embedded local engine.

    Requires the smol-machines Python SDK (``smol``), whose local backend embeds
    the smolvm engine and does not require a separate ``smolvm serve`` process.
    File/search/edit helpers are implemented on top of exec.
    """

    capabilities = SandboxCapabilities(
        exec=True,
        read_file=True,
        write_file=True,
        glob=True,
        grep=True,
        volumes=True,
        persist=True,
        export_import=True,
    )

    def __init__(self, profile: SandboxProfile):
        super().__init__(profile)
        self._machine: Any | None = None

    async def _start_provider(self) -> None:
        try:
            from smol import (  # type: ignore[import-not-found]
                Machine,
                MachineConfig,
                MountSpec,
                ResourceSpec,
            )
        except ImportError as e:
            raise SandboxProviderError(
                "smol sandbox provider requires the smol-machines Python SDK. "
                "Install it with `pip install smolmachines`."
            ) from e

        try:
            mounts = [
                MountSpec(
                    source=mount.source,
                    target=mount.target,
                    read_only=mount.mode.lower() == "ro",
                )
                for mount in self.profile.volumes
            ]
            resources = ResourceSpec(
                cpus=self.profile.resources.cpu,
                memory_mb=self.profile.resources.memory_mb,
                network=self.profile.network.enabled,
                allow_hosts=list(self.profile.network.allow_hosts) or None,
            )
            config = MachineConfig(
                name=self.profile.sandbox_id,
                image=self.profile.image,
                mounts=mounts or None,
                resources=resources,
                persistent=self.profile.persist,
            )
            try:
                self._machine = await asyncio.to_thread(Machine.create, config)
            except Exception as e:
                if self.profile.persist and _is_already_exists_error(e):
                    self._machine = await asyncio.to_thread(
                        Machine.connect, self.profile.sandbox_id
                    )
                else:
                    raise
        except Exception as e:  # pragma: no cover - provider-specific
            raise SandboxProviderError(f"Failed to start smol sandbox: {e}") from e

    async def _exec_provider(
        self,
        command: str | list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> SandboxExecResult:
        if self._machine is None:
            raise SandboxProviderError("smol sandbox is not started.")
        try:
            from smol import ExecOptions  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover - already checked at start
            raise SandboxProviderError("smol sandbox provider is unavailable.") from e

        args = split_command(command)
        opts = ExecOptions(
            env=env,
            workdir=cwd,
            timeout=None if timeout is None else int(timeout),
        )
        try:
            result = await asyncio.to_thread(self._machine.exec, args, opts)
            return normalize_exec_result(result)
        except Exception as e:  # pragma: no cover - provider-specific
            raise SandboxProviderError(f"smol exec failed: {e}") from e

    async def close(self) -> None:
        if self._machine is not None and not self.profile.persist:
            await asyncio.to_thread(self._machine.delete)
        self._machine = None
        self._started = False
