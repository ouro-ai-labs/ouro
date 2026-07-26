"""Sandbox provider adapter factory."""

from __future__ import annotations

from ouro.core.sandbox import SandboxSession

from ..manager import SandboxProfile
from .base import SandboxProviderError


def create_sandbox_session(profile: SandboxProfile) -> SandboxSession:
    if profile.provider == "boxlite":
        from .boxlite import BoxLiteSandboxSession

        return BoxLiteSandboxSession(profile)
    if profile.provider == "smolvm":
        from .smolvm import SmolVMSandboxSession

        return SmolVMSandboxSession(profile)
    raise SandboxProviderError(
        f"Unsupported sandbox provider '{profile.provider}'. Supported: boxlite, smolvm."
    )


__all__ = ["SandboxProviderError", "create_sandbox_session"]
