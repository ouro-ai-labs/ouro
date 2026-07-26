import builtins
import sys
from types import SimpleNamespace

import pytest

from ouro.capabilities.sandbox import ResourceConfig, SandboxProfile, VolumeMount
from ouro.capabilities.sandbox.adapters.base import ExecOnlySandboxSession, SandboxProviderError
from ouro.capabilities.sandbox.adapters.boxlite import BoxLiteSandboxSession
from ouro.capabilities.sandbox.adapters.smolvm import SmolVMSandboxSession


def _block_import(monkeypatch, blocked_name: str):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == blocked_name:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


class LazyStartSession(ExecOnlySandboxSession):
    def __init__(self):
        super().__init__(
            SandboxProfile(sandbox_id="lazy", provider="smolvm", image="python:alpine")
        )
        self.start_count = 0
        self.exec_count = 0

    async def _start_provider(self) -> None:
        self.start_count += 1

    async def _exec_provider(self, command, *, cwd=None, env=None, timeout=None):
        from ouro.core.sandbox import SandboxExecResult

        self.exec_count += 1
        if "base.glob" in command:
            return SandboxExecResult(stdout='{"matches": ["/workspace/a.py"]}', exit_code=0)
        if "path.write_text" in command:
            return SandboxExecResult(stdout="", exit_code=0)
        if "base.rglob" in command:
            return SandboxExecResult(stdout="Found 0 files\n", exit_code=0)
        return SandboxExecResult(stdout="hello\n", exit_code=0)


async def test_helper_file_methods_lazy_start_before_exec():
    session = LazyStartSession()

    assert await session.read_file("/workspace/a.txt") == "hello\n"
    await session.write_file("/workspace/a.txt", "hello")
    assert await session.glob("*.py", path="/workspace") == ["/workspace/a.py"]
    assert await session.grep("hello", path="/workspace") == "Found 0 files"

    assert session.start_count == 1
    assert session.exec_count == 4


async def test_boxlite_start_passes_profile_options(monkeypatch):
    calls = []

    class FakeSimpleBox:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def start(self):
            return None

    monkeypatch.setitem(sys.modules, "boxlite", SimpleNamespace(SimpleBox=FakeSimpleBox))

    profile = SandboxProfile(
        sandbox_id="box",
        provider="boxlite",
        image="python:3.12-slim",
        working_dir="/workspace",
        persist=False,
        resources=ResourceConfig(cpu=2, memory_mb=4096),
        volumes=[
            VolumeMount(source="/host/project", target="/workspace", mode="rw"),
            VolumeMount(source="/host/cache", target="/cache", mode="ro"),
        ],
    )
    session = BoxLiteSandboxSession(profile)

    await session.start()

    assert calls == [
        {
            "image": "python:3.12-slim",
            "auto_remove": True,
            "working_dir": "/workspace",
            "cpus": 2,
            "memory_mib": 4096,
            "volumes": [
                ("/host/project", "/workspace", False),
                ("/host/cache", "/cache", True),
            ],
        }
    ]


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
