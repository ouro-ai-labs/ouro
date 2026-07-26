"""BoxLite sandbox provider."""

from __future__ import annotations

from typing import Any

from ouro.core.sandbox import SandboxCapabilities, SandboxExecResult

from ..manager import SandboxProfile
from .base import ExecOnlySandboxSession, SandboxProviderError, normalize_exec_result, split_command


class BoxLiteSandboxSession(ExecOnlySandboxSession):
    """SDK-first BoxLite session.

    The adapter intentionally maps only stable, first-slice fields directly
    (image + exec). File/search/edit tools are implemented on top of exec.
    """

    capabilities = SandboxCapabilities(
        exec=True,
        read_file=True,
        write_file=True,
        glob=True,
        grep=True,
        volumes=True,
        file_copy=True,
        persist=True,
        clone=True,
        export_import=True,
    )

    def __init__(self, profile: SandboxProfile):
        super().__init__(profile)
        self._box: Any | None = None

    async def _start_provider(self) -> None:
        try:
            import boxlite  # type: ignore[import-not-found]
        except ImportError as e:
            raise SandboxProviderError(
                "BoxLite sandbox provider requires `pip install boxlite`."
            ) from e

        image = self.profile.image
        if not image:
            raise SandboxProviderError("BoxLite sandbox requires an `image` in sandboxes.yaml.")

        options: dict[str, Any] = {
            "image": image,
            "auto_remove": not self.profile.persist,
        }
        if self.profile.working_dir:
            options["working_dir"] = self.profile.working_dir
        if self.profile.resources.cpu is not None:
            options["cpus"] = self.profile.resources.cpu
        if self.profile.resources.memory_mb is not None:
            options["memory_mib"] = self.profile.resources.memory_mb
        if self.profile.volumes:
            options["volumes"] = [
                (mount.source, mount.target, mount.mode.lower() == "ro")
                for mount in self.profile.volumes
            ]

        try:
            self._box = boxlite.SimpleBox(**options)
            # Some SDK versions require explicit async start, others start lazily.
            start = getattr(self._box, "start", None)
            if start is not None:
                result = start()
                if hasattr(result, "__await__"):
                    await result
        except Exception as e:  # pragma: no cover - provider-specific
            raise SandboxProviderError(f"Failed to start BoxLite sandbox: {e}") from e

    async def _exec_provider(
        self,
        command: str | list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> SandboxExecResult:
        if self._box is None:
            raise SandboxProviderError("BoxLite sandbox is not started.")
        args = split_command(command)
        try:
            kwargs = {}
            if cwd is not None:
                kwargs["cwd"] = cwd
            if env is not None:
                kwargs["env"] = env
            if timeout is not None:
                kwargs["timeout"] = timeout
            result = await self._box.exec(*args, **kwargs)
            return normalize_exec_result(result)
        except TypeError:
            # Older/minimal SDK surface: retry without optional kwargs.
            result = await self._box.exec(*args)
            return normalize_exec_result(result)
        except Exception as e:  # pragma: no cover - provider-specific
            raise SandboxProviderError(f"BoxLite exec failed: {e}") from e

    async def close(self) -> None:
        if self._box is not None and not self.profile.persist:
            close = getattr(self._box, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result
        self._box = None
        self._started = False
