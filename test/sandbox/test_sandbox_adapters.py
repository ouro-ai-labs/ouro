import builtins

import pytest

from ouro.capabilities.sandbox import SandboxProfile
from ouro.capabilities.sandbox.adapters.base import SandboxProviderError
from ouro.capabilities.sandbox.adapters.boxlite import BoxLiteSandboxSession
from ouro.capabilities.sandbox.adapters.smolvm import SmolVMSandboxSession


def _block_import(monkeypatch, blocked_name: str):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == blocked_name:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


async def test_boxlite_missing_sdk_error(monkeypatch):
    _block_import(monkeypatch, "boxlite")
    profile = SandboxProfile(sandbox_id="box", provider="boxlite", image="python:slim")
    session = BoxLiteSandboxSession(profile)
    with pytest.raises(SandboxProviderError, match="pip install boxlite"):
        await session.start()


async def test_smolvm_missing_sdk_error(monkeypatch):
    _block_import(monkeypatch, "smolvm")
    profile = SandboxProfile(sandbox_id="smol", provider="smolvm", image="python:alpine")
    session = SmolVMSandboxSession(profile)
    with pytest.raises(SandboxProviderError, match="pip install smolvm"):
        await session.start()
