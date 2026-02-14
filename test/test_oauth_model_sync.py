from llm.model_manager import ModelManager
from llm.oauth_model_sync import remove_oauth_models, sync_oauth_models


def _write_models_yaml(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_sync_oauth_models_adds_chatgpt_models(tmp_path):
    config_path = tmp_path / "models.yaml"
    _write_models_yaml(
        config_path,
        "\n".join(
            [
                "models:",
                "  openai/gpt-4o:",
                "    api_key: test",
                "default: openai/gpt-4o",
                "",
            ]
        ),
    )

    manager = ModelManager(config_path=str(config_path))
    added = sync_oauth_models(manager, "chatgpt")

    assert added
    assert "chatgpt/gpt-5.2-codex" in manager.models
    assert "chatgpt/gpt-5.3-codex" in manager.models
    assert manager.models["chatgpt/gpt-5.2-codex"].extra.get("oauth_managed") is True


def test_remove_oauth_models_removes_only_managed_entries(tmp_path):
    config_path = tmp_path / "models.yaml"
    _write_models_yaml(
        config_path,
        "\n".join(
            [
                "models:",
                "  chatgpt/gpt-5.2-codex:",
                "    timeout: 600",
                "    oauth_managed: true",
                "    oauth_provider: chatgpt",
                "  chatgpt/gpt-5.2:",
                "    timeout: 600",
                "  openai/gpt-4o:",
                "    api_key: test",
                "default: chatgpt/gpt-5.2-codex",
                "",
            ]
        ),
    )

    manager = ModelManager(config_path=str(config_path))
    removed = remove_oauth_models(manager, "chatgpt")

    assert "chatgpt/gpt-5.2-codex" in removed
    assert "chatgpt/gpt-5.2-codex" not in manager.models
    # Unmanaged entry should remain
    assert "chatgpt/gpt-5.2" in manager.models
    # Default should be repaired
    assert manager.default_model_id in manager.models


def test_remove_oauth_models_removes_stale_managed_entries(tmp_path):
    config_path = tmp_path / "models.yaml"
    _write_models_yaml(
        config_path,
        "\n".join(
            [
                "models:",
                "  chatgpt/legacy-codex:",
                "    timeout: 600",
                "    oauth_managed: true",
                "    oauth_provider: chatgpt",
                "  openai/gpt-4o:",
                "    api_key: test",
                "default: chatgpt/legacy-codex",
                "",
            ]
        ),
    )

    manager = ModelManager(config_path=str(config_path))
    removed = remove_oauth_models(manager, "chatgpt")

    assert removed == ["chatgpt/legacy-codex"]
    assert "chatgpt/legacy-codex" not in manager.models
    assert manager.default_model_id in manager.models
