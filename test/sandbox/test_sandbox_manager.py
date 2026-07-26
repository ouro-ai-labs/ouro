from ouro.capabilities.sandbox import SandboxManager


def test_sandbox_manager_creates_template(tmp_path):
    config = tmp_path / "sandboxes.yaml"

    manager = SandboxManager(config_path=str(config))

    assert config.exists()
    assert manager.list_sandboxes() == []
    assert "Sandbox Configuration" in config.read_text()


def test_sandbox_manager_loads_and_switches_profiles(tmp_path):
    config = tmp_path / "sandboxes.yaml"
    config.write_text(
        """
sandboxes:
  smol:
    provider: smolvm
    api_url: http://127.0.0.1:8080
    image: python:3.12-alpine
    working_dir: /workspace
    persist: true
    network:
      enabled: true
      allow_hosts: [pypi.org]
    resources:
      cpu: 2
      memory_mb: 1024
    volumes:
      - source: .
        target: /workspace
        mode: rw
  box:
    provider: boxlite
    image: python:3.12-slim
default: smol
current: smol
""".strip()
    )

    manager = SandboxManager(config_path=str(config))

    current = manager.get_current_sandbox()
    assert current is not None
    assert current.sandbox_id == "smol"
    assert current.provider == "smolvm"
    assert current.network.enabled is True
    assert current.network.allow_hosts == ["pypi.org"]
    assert current.resources.cpu == 2
    assert current.volumes[0].target == "/workspace"

    switched = manager.switch_sandbox("box")
    assert switched is not None
    assert switched.provider == "boxlite"
    assert SandboxManager(config_path=str(config)).get_current_sandbox().sandbox_id == "box"


def test_sandbox_manager_validates_required_fields(tmp_path):
    config = tmp_path / "sandboxes.yaml"
    config.write_text(
        """
sandboxes:
  bad:
    provider: unknown
    image: python:3.12
default: bad
current: bad
""".strip()
    )
    manager = SandboxManager(config_path=str(config))
    profile = manager.get_current_sandbox()
    ok, message = manager.validate_sandbox(profile)
    assert ok is False
    assert "Unsupported sandbox provider" in message
