"""Sandbox primitive types shared across ouro layers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SandboxExecResult:
    """Result of executing a command inside a sandbox."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    duration_ms: int | None = None


@dataclass(frozen=True)
class SandboxCapabilities:
    """Optional provider capabilities exposed for routing and UX."""

    exec: bool = True
    read_file: bool = True
    write_file: bool = True
    glob: bool = True
    grep: bool = True
    volumes: bool = False
    file_copy: bool = False
    persist: bool = False
    clone: bool = False
    export_import: bool = False
    snapshot: bool = False
