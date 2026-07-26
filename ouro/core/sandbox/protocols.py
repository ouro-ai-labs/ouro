"""Sandbox protocols used by capabilities without binding to one provider."""

from __future__ import annotations

from typing import Protocol

from .types import SandboxCapabilities, SandboxExecResult


class SandboxSession(Protocol):
    """A running or lazily-started isolated execution environment."""

    id: str
    provider: str
    capabilities: SandboxCapabilities

    async def start(self) -> None: ...

    async def exec(
        self,
        command: str | list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> SandboxExecResult: ...

    async def read_file(self, path: str, *, offset: int = 0, limit: int | None = None) -> str: ...

    async def write_file(self, path: str, content: str) -> None: ...

    async def glob(self, pattern: str, *, path: str = ".") -> list[str]: ...

    async def grep(
        self,
        pattern: str,
        *,
        path: str = ".",
        mode: str = "files_only",
        case_sensitive: bool = True,
        file_pattern: str | None = None,
        context_lines: int = 0,
        head_limit: int | None = None,
        offset: int = 0,
    ) -> str: ...

    async def close(self) -> None: ...
