from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "update_oauth_model_catalog.py"
    spec = importlib.util.spec_from_file_location("update_oauth_model_catalog", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_provider_block_handles_braces_inside_strings():
    m = _load_module()
    models_js = """
export const MODELS = {
  "openai-codex": {
    "gpt-5.2-codex": {
      id: "gpt-5.2-codex",
      note: "example with { brace } in string"
    },
    "gpt-5.2-codex-spark": {
      id: "gpt-5.2-codex-spark"
    }
  },
  "other": {}
}
"""

    block = m._extract_provider_block(models_js, "openai-codex")

    assert '"gpt-5.2-codex": {' in block
    assert '"gpt-5.2-codex-spark": {' in block


def test_extract_provider_model_ids_uses_top_level_keys_only():
    m = _load_module()
    provider_block = """
  "gpt-5.2-codex": {
    id: "gpt-5.2-codex",
    nested: {
      "not-a-model": {
        value: 1
      }
    }
  },
  "gpt-5.2-codex-spark": {
    id: "gpt-5.2-codex-spark"
  }
"""

    ids = m._extract_provider_model_ids(provider_block)

    assert ids == ["gpt-5.2-codex", "gpt-5.2-codex-spark"]


def test_render_catalog_module_maps_prefix():
    m = _load_module()

    rendered = m._render_catalog_module("0.52.12", ["gpt-5.2-codex"])

    assert 'PI_AI_VERSION = "0.52.12"' in rendered
    assert '"chatgpt/gpt-5.2-codex"' in rendered


def test_filter_model_ids_for_litellm_keeps_supported_only(monkeypatch):
    m = _load_module()
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(chatgpt_models={"chatgpt/gpt-5.2-codex"}),
    )

    result = m._filter_model_ids_for_litellm(["gpt-5.2-codex", "gpt-5.3-codex"])

    assert result == ["gpt-5.2-codex"]


def test_filter_model_ids_for_litellm_can_return_empty(monkeypatch):
    m = _load_module()
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(chatgpt_models={"chatgpt/gpt-5.2-codex"}),
    )

    result = m._filter_model_ids_for_litellm(["gpt-5.3-codex"])

    assert result == []
