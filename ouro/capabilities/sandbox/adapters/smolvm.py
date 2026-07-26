"""smolvm sandbox provider."""

from __future__ import annotations

from typing import Any

from ouro.core.sandbox import SandboxCapabilities, SandboxExecResult

from ..manager import SandboxProfile
from .base import ExecOnlySandboxSession, SandboxProviderError, normalize_exec_result, split_command


class SmolVMSandboxSession(ExecOnlySandboxSession):
    """SDK-first smolvm session.

    Requires the smolvm Python SDK and a running smolvm server (default
    http://127.0.0.1:8080). The first slice uses exec/run plus helper scripts
    for file operations.
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
        self._sandbox: Any | None = None

    async def _start_provider(self) -> None:
        try:
            from smolvm import Sandbox, SandboxConfig  # type: ignore[import-not-found]
        except ImportError as e:
            raise SandboxProviderError(
                "smolvm sandbox provider requires `pip install smolvm` and a running smolvm server."
            ) from e

        try:
            config_kwargs: dict[str, Any] = {"name": self.profile.sandbox_id}
            if self.profile.image:
                config_kwargs["image"] = self.profile.image
            if self.profile.api_url:
                config_kwargs["api_url"] = self.profile.api_url
            while True:
                try:
                    config = SandboxConfig(**config_kwargs)
                    break
                except TypeError:
                    # SDK versions may differ on optional constructor fields.
                    if "api_url" in config_kwargs:
                        config_kwargs.pop("api_url")
                        continue
                    if "image" in config_kwargs:
                        config_kwargs.pop("image")
                        continue
                    raise
            self._sandbox = Sandbox(config)
            await self._sandbox.start()
        except Exception as e:  # pragma: no cover - provider-specific
            raise SandboxProviderError(f"Failed to start smolvm sandbox: {e}") from e

    async def _exec_provider(
        self,
        command: str | list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> SandboxExecResult:
        if self._sandbox is None:
            raise SandboxProviderError("smolvm sandbox is not started.")
        args = split_command(command)
        try:
            kwargs = {}
            if cwd is not None:
                kwargs["cwd"] = cwd
            if env is not None:
                kwargs["env"] = env
            if timeout is not None:
                kwargs["timeout"] = timeout
            # Prefer direct microVM exec. If a provider version lacks optional kwargs,
            # retry with command only.
            try:
                result = await self._sandbox.exec(args, **kwargs)
            except TypeError:
                result = await self._sandbox.exec(args)
            return normalize_exec_result(result)
        except Exception as e:  # pragma: no cover - provider-specific
            raise SandboxProviderError(f"smolvm exec failed: {e}") from e

    async def close(self) -> None:
        if self._sandbox is not None and not self.profile.persist:
            stop = getattr(self._sandbox, "stop", None)
            if stop is not None:
                result = stop()
                if hasattr(result, "__await__"):
                    await result
        self._sandbox = None
        self._started = False
