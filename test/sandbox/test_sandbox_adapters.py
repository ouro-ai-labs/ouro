import builtins
import sys
from types import SimpleNamespace

import pytest

from ouro.capabilities.sandbox import NetworkConfig, ResourceConfig, SandboxProfile, VolumeMount
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


async def test_smolvm_start_uses_latest_smol_sdk(monkeypatch):
    calls = []

    class FakeMountSpec:
        def __init__(self, *, source, target, read_only=False):
            self.source = source
            self.target = target
            self.read_only = read_only

        def __eq__(self, other):
            return self.__dict__ == getattr(other, "__dict__", {})

    class FakeResourceSpec:
        def __init__(self, *, cpus=None, memory_mb=None, network=None, allow_hosts=None):
            self.cpus = cpus
            self.memory_mb = memory_mb
            self.network = network
            self.allow_hosts = allow_hosts

        def __eq__(self, other):
            return self.__dict__ == getattr(other, "__dict__", {})

    class FakeMachineConfig:
        def __init__(self, **kwargs):
            calls.append(("config", kwargs))
            self.kwargs = kwargs

    class FakeMachine:
        @classmethod
        def create(cls, config):
            calls.append(("create", config.kwargs))
            return cls()

    monkeypatch.setitem(
        sys.modules,
        "smol",
        SimpleNamespace(
            Machine=FakeMachine,
            MachineConfig=FakeMachineConfig,
            MountSpec=FakeMountSpec,
            ResourceSpec=FakeResourceSpec,
        ),
    )

    profile = SandboxProfile(
        sandbox_id="smol",
        provider="smolvm",
        image="python:3.12-alpine",
        working_dir="/workspace",
        persist=True,
        network=NetworkConfig(enabled=True, allow_hosts=["registry.npmjs.org"]),
        resources=ResourceConfig(cpu=2, memory_mb=4096),
        volumes=[VolumeMount(source="/host/project", target="/workspace", mode="rw")],
    )
    session = SmolVMSandboxSession(profile)

    await session.start()

    expected = {
        "name": "smol",
        "image": "python:3.12-alpine",
        "mounts": [FakeMountSpec(source="/host/project", target="/workspace")],
        "resources": FakeResourceSpec(
            cpus=2,
            memory_mb=4096,
            network=True,
            allow_hosts=["registry.npmjs.org"],
        ),
        "persistent": True,
    }
    assert calls == [("config", expected), ("create", expected)]


async def test_smolvm_exec_uses_exec_options(monkeypatch):
    from ouro.core.sandbox import SandboxExecResult

    class FakeExecOptions:
        def __init__(self, *, env=None, workdir=None, timeout=None):
            self.env = env
            self.workdir = workdir
            self.timeout = timeout

    class FakeMachine:
        def exec(self, args, opts):
            assert args == ["sh", "-lc", "pwd"]
            assert opts.__dict__ == {
                "env": {"A": "B"},
                "workdir": "/workspace",
                "timeout": 5,
            }
            return SandboxExecResult(stdout="/workspace\n", exit_code=0)

    monkeypatch.setitem(sys.modules, "smol", SimpleNamespace(ExecOptions=FakeExecOptions))

    session = SmolVMSandboxSession(
        SandboxProfile(sandbox_id="smol", provider="smolvm", image="python:alpine")
    )
    session._machine = FakeMachine()

    result = await session._exec_provider(
        "pwd",
        cwd="/workspace",
        env={"A": "B"},
        timeout=5,
    )

    assert result.stdout == "/workspace\n"


async def test_smolvm_missing_sdk_error(monkeypatch):
    _block_import(monkeypatch, "smol")
    profile = SandboxProfile(sandbox_id="smol", provider="smolvm", image="python:alpine")
    session = SmolVMSandboxSession(profile)
    with pytest.raises(SandboxProviderError, match="smol-machines Python SDK"):
        await session.start()
