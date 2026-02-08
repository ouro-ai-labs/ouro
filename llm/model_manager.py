"""Model manager for handling multiple models with YAML persistence."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from utils import get_logger

logger = get_logger(__name__)

DEFAULT_CONFIG_TEMPLATE = """# Model Configuration
# This file is gitignored - do not commit to version control
#
# The key under `models` is the LiteLLM model ID (provider/model).
# Fill in `api_key` directly in this file.
#
# Supported fields:
#   - api_key: API key (required for most hosted providers)
#   - api_base: Custom base URL (optional)
#   - timeout: Request timeout in seconds (default: 600)
#   - drop_params: Drop unsupported params (default: true)

models:
  # openai/gpt-4o:
  #   api_key: sk-...
  #   timeout: 300
  # anthropic/claude-3-5-sonnet-20241022:
  #   api_key: sk-ant-...
  # ollama/llama2:
  #   api_base: http://localhost:11434
default: null
"""


def _coerce_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


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


def _is_local_api_base(api_base: str | None) -> bool:
    if not api_base:
        return False
    raw = str(api_base).strip()
    if not raw:
        return False
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


@dataclass
class ModelProfile:
    """Configuration for a single model."""

    model_id: str  # LiteLLM model ID (e.g. "openai/gpt-4o")
    api_key: str | None = None
    api_base: str | None = None
    timeout: int = 600
    drop_params: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def provider(self) -> str:
        return self.model_id.split("/")[0] if "/" in self.model_id else "unknown"

    @property
    def display_name(self) -> str:
        return self.model_id

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"timeout": self.timeout, "drop_params": self.drop_params}
        if self.api_key:
            result["api_key"] = self.api_key
        if self.api_base is not None:
            result["api_base"] = self.api_base
        if self.extra:
            result.update(self.extra)
        return result


class ModelManager:
    """Manages multiple models with YAML persistence."""

    CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".ouro", "models.yaml")

    def __init__(self, config_path: str | None = None):
        self.config_path = config_path or self.CONFIG_PATH
        self.models: dict[str, ModelProfile] = {}
        self.default_model_id: str | None = None
        self.current_model_id: str | None = None
        self._load()

    def _ensure_yaml(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "PyYAML is required for model configuration. Install it (e.g. `uv add pyyaml`)."
            ) from e

    def _atomic_write(self, content: str) -> None:
        directory = os.path.dirname(self.config_path) or "."
        os.makedirs(directory, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(prefix=".models.", suffix=".tmp", dir=directory)
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
        self._atomic_write(DEFAULT_CONFIG_TEMPLATE)
        logger.info(f"Created model config template at {self.config_path}")

    def _load(self) -> None:
        self._ensure_yaml()
        import yaml

        if not os.path.exists(self.config_path):
            self._create_default_config()

        with open(self.config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        models = config.get("models") or {}
        if not isinstance(models, dict):
            logger.warning("Invalid models.yaml format: 'models' should be a mapping")
            models = {}

        for model_id, data in models.items():
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            if not isinstance(data, dict):
                logger.warning(f"Invalid model config for '{model_id}', skipping")
                continue

            api_key = data.get("api_key")
            api_base = data.get("api_base")
            timeout = _coerce_int(data.get("timeout"), default=600)
            drop_params = _coerce_bool(data.get("drop_params"), default=True)
            extra = {
                k: v
                for k, v in data.items()
                if k not in {"name", "api_key", "api_base", "timeout", "drop_params"}
            }

            self.models[model_id] = ModelProfile(
                model_id=model_id,
                api_key=None if api_key is None else str(api_key),
                api_base=None if api_base is None else str(api_base),
                timeout=timeout,
                drop_params=drop_params,
                extra=extra,
            )

        default = config.get("default")
        self.default_model_id = default if isinstance(default, str) else None
        if self.default_model_id not in self.models:
            self.default_model_id = next(iter(self.models.keys()), None)

        self.current_model_id = self.default_model_id
        logger.info(f"Loaded {len(self.models)} models from {self.config_path}")

    def _save(self) -> None:
        self._ensure_yaml()
        import yaml

        config = {
            "models": {mid: profile.to_dict() for mid, profile in self.models.items()},
            "default": self.default_model_id,
        }
        header = "# Model Configuration\n# This file is gitignored - do not commit to version control\n\n"
        body = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
        self._atomic_write(header + body)

    def is_configured(self) -> bool:
        return bool(self.models) and bool(self.default_model_id)

    def get_model(self, model_id: str) -> ModelProfile | None:
        return self.models.get(model_id)

    def list_models(self) -> list[ModelProfile]:
        return list(self.models.values())

    def get_model_ids(self) -> list[str]:
        return list(self.models.keys())

    def get_default_model_id(self) -> str | None:
        return self.default_model_id

    def get_current_model(self) -> ModelProfile | None:
        if not self.current_model_id:
            return None
        return self.models.get(self.current_model_id)

    def set_default(self, model_id: str) -> bool:
        if model_id not in self.models:
            return False
        self.default_model_id = model_id
        if not self.current_model_id:
            self.current_model_id = model_id
        self._save()
        return True

    def switch_model(self, model_id: str) -> ModelProfile | None:
        if model_id not in self.models:
            return None
        self.current_model_id = model_id
        return self.get_current_model()

    def validate_model(self, model: ModelProfile) -> tuple[bool, str]:
        """Validate a model has required configuration."""
        if not model.model_id:
            return False, "Model ID is missing."
        if (
            model.provider not in {"ollama", "localhost"}
            and not _is_local_api_base(model.api_base)
            and not (model.api_key or "").strip()
        ):
            return (
                False,
                f"API key not configured for {model.provider}. "
                f"Edit `{self.config_path}` and set models['{model.model_id}'].api_key.",
            )
        return True, ""

    def reload(self) -> None:
        self.models.clear()
        self.default_model_id = None
        self.current_model_id = None
        self._load()
