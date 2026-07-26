"""Sandbox profile manager with YAML persistence."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from ouro.core.log import get_logger

logger = get_logger(__name__)

DEFAULT_SANDBOX_CONFIG_TEMPLATE = """# Sandbox Configuration
# This file is gitignored - do not commit secrets.
#
# Sandboxes are optional isolated execution environments. When enabled,
# ouro routes shell/file/edit/search tools into the selected sandbox.
#
# Install providers separately:
#   - BoxLite: pip install boxlite
#   - smolvm:  pip install smolvm and run the smolvm server (default http://127.0.0.1:8080)

sandboxes:
  # smolvm-local:
  #   provider: smolvm
  #   api_url: http://127.0.0.1:8080
  #   image: python:3.12-alpine
  #   working_dir: /workspace
  #   persist: true
  #   network:
  #     enabled: false
  #     allow_hosts: []
  #   resources:
  #     cpu: 2
  #     memory_mb: 4096
  #   volumes:
  #     - source: .
  #       target: /workspace
  #       mode: rw
  # boxlite-local:
  #   provider: boxlite
  #   image: python:3.12-slim
  #   working_dir: /workspace
  #   persist: true
  #   network:
  #     enabled: false
  #     allow_hosts: []

default: null
current: null
"""


@dataclass(frozen=True)
class NetworkConfig:
    enabled: bool = False
    allow_hosts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResourceConfig:
    cpu: int | None = None
    memory_mb: int | None = None


@dataclass(frozen=True)
class VolumeMount:
    source: str
    target: str
    mode: str = "rw"


@dataclass(frozen=True)
class SandboxProfile:
    sandbox_id: str
    provider: str
    image: str | None = None
    api_url: str | None = None
    working_dir: str = "/workspace"
    persist: bool = True
    network: NetworkConfig = field(default_factory=NetworkConfig)
    resources: ResourceConfig = field(default_factory=ResourceConfig)
    volumes: list[VolumeMount] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "provider": self.provider,
            "working_dir": self.working_dir,
            "persist": self.persist,
            "network": {
                "enabled": self.network.enabled,
                "allow_hosts": list(self.network.allow_hosts),
            },
            "resources": {
                "cpu": self.resources.cpu,
                "memory_mb": self.resources.memory_mb,
            },
            "volumes": [mount.__dict__.copy() for mount in self.volumes],
        }
        if self.image is not None:
            data["image"] = self.image
        if self.api_url is not None:
            data["api_url"] = self.api_url
        data.update(self.extra)
        return data


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "y", "on"}:
            return True
        if v in {"false", "0", "no", "n", "off"}:
            return False
    return default


def _coerce_int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


class SandboxManager:
    """Manages sandbox profiles in ~/.ouro/sandboxes.yaml."""

    CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".ouro", "sandboxes.yaml")

    def __init__(self, config_path: str | None = None):
        self.config_path = config_path or self.CONFIG_PATH
        self.sandboxes: dict[str, SandboxProfile] = {}
        self.default_sandbox_id: str | None = None
        self.current_sandbox_id: str | None = None
        self._load()

    def _ensure_yaml(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError as e:
            raise RuntimeError("PyYAML is required for sandbox configuration.") from e

    def _atomic_write(self, content: str) -> None:
        directory = os.path.dirname(self.config_path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".sandboxes.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, self.config_path)
            with suppress(OSError):
                os.chmod(self.config_path, 0o600)
        finally:
            with suppress(OSError):
                os.unlink(tmp_path)

    def _create_default_config(self) -> None:
        self._atomic_write(DEFAULT_SANDBOX_CONFIG_TEMPLATE)
        logger.info(f"Created sandbox config template at {self.config_path}")

    def _load(self) -> None:
        self._ensure_yaml()
        import yaml

        if not os.path.exists(self.config_path):
            self._create_default_config()

        with open(self.config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        raw_sandboxes = config.get("sandboxes") or {}
        if not isinstance(raw_sandboxes, dict):
            logger.warning("Invalid sandboxes.yaml format: 'sandboxes' should be a mapping")
            raw_sandboxes = {}

        for sandbox_id, data in raw_sandboxes.items():
            if not isinstance(sandbox_id, str) or not sandbox_id.strip():
                continue
            if not isinstance(data, dict):
                logger.warning(f"Invalid sandbox config for '{sandbox_id}', skipping")
                continue
            profile = self._parse_profile(sandbox_id, data)
            if profile is not None:
                self.sandboxes[sandbox_id] = profile

        default = config.get("default")
        self.default_sandbox_id = default if isinstance(default, str) else None
        if self.default_sandbox_id not in self.sandboxes:
            self.default_sandbox_id = next(iter(self.sandboxes.keys()), None)

        current = config.get("current")
        self.current_sandbox_id = current if isinstance(current, str) else self.default_sandbox_id
        if self.current_sandbox_id not in self.sandboxes:
            self.current_sandbox_id = self.default_sandbox_id

    def _parse_profile(self, sandbox_id: str, data: dict[str, Any]) -> SandboxProfile | None:
        provider = data.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            logger.warning(f"Sandbox '{sandbox_id}' missing provider, skipping")
            return None

        network_data = data.get("network") if isinstance(data.get("network"), dict) else {}
        allow_hosts = network_data.get("allow_hosts", []) if isinstance(network_data, dict) else []
        if not isinstance(allow_hosts, list):
            allow_hosts = []
        network = NetworkConfig(
            enabled=_coerce_bool(
                network_data.get("enabled") if isinstance(network_data, dict) else None, False
            ),
            allow_hosts=[str(host) for host in allow_hosts if str(host).strip()],
        )

        resources_data = data.get("resources") if isinstance(data.get("resources"), dict) else {}
        resources = ResourceConfig(
            cpu=_coerce_int_or_none(
                resources_data.get("cpu") if isinstance(resources_data, dict) else None
            ),
            memory_mb=_coerce_int_or_none(
                resources_data.get("memory_mb") if isinstance(resources_data, dict) else None
            ),
        )

        mounts: list[VolumeMount] = []
        raw_volumes = data.get("volumes") or []
        if isinstance(raw_volumes, list):
            for item in raw_volumes:
                if not isinstance(item, dict):
                    continue
                source = item.get("source")
                target = item.get("target")
                if not isinstance(source, str) or not isinstance(target, str):
                    continue
                mode = item.get("mode", "rw")
                mounts.append(VolumeMount(source=source, target=target, mode=str(mode)))

        known = {
            "provider",
            "image",
            "api_url",
            "working_dir",
            "persist",
            "network",
            "resources",
            "volumes",
        }
        extra = {k: v for k, v in data.items() if k not in known}

        image = data.get("image")
        api_url = data.get("api_url")
        working_dir = data.get("working_dir", "/workspace")
        return SandboxProfile(
            sandbox_id=sandbox_id,
            provider=provider.strip().lower(),
            image=None if image is None else str(image),
            api_url=None if api_url is None else str(api_url),
            working_dir=str(working_dir) if working_dir else "/workspace",
            persist=_coerce_bool(data.get("persist"), True),
            network=network,
            resources=resources,
            volumes=mounts,
            extra=extra,
        )

    def _save(self) -> None:
        self._ensure_yaml()
        import yaml

        config = {
            "sandboxes": {sid: profile.to_dict() for sid, profile in self.sandboxes.items()},
            "default": self.default_sandbox_id,
            "current": self.current_sandbox_id,
        }
        header = "# Sandbox Configuration\n# This file is gitignored - do not commit secrets.\n\n"
        self._atomic_write(header + yaml.safe_dump(config, sort_keys=False, allow_unicode=True))

    def is_configured(self) -> bool:
        return bool(self.sandboxes) and bool(self.default_sandbox_id)

    def get_sandbox(self, sandbox_id: str) -> SandboxProfile | None:
        return self.sandboxes.get(sandbox_id)

    def list_sandboxes(self) -> list[SandboxProfile]:
        return list(self.sandboxes.values())

    def get_sandbox_ids(self) -> list[str]:
        return list(self.sandboxes.keys())

    def get_current_sandbox(self) -> SandboxProfile | None:
        if not self.current_sandbox_id:
            return None
        return self.sandboxes.get(self.current_sandbox_id)

    def switch_sandbox(self, sandbox_id: str) -> SandboxProfile | None:
        if sandbox_id not in self.sandboxes:
            return None
        self.current_sandbox_id = sandbox_id
        self._save()
        return self.get_current_sandbox()

    def validate_sandbox(self, profile: SandboxProfile) -> tuple[bool, str]:
        if profile.provider not in {"boxlite", "smolvm"}:
            return (
                False,
                f"Unsupported sandbox provider '{profile.provider}'. Supported: boxlite, smolvm.",
            )
        if not profile.image:
            return False, f"Sandbox '{profile.sandbox_id}' must configure an OCI image."
        return True, ""
