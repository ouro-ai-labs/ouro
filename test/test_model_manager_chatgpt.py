from llm import ModelManager


def test_validate_chatgpt_model_without_api_key(tmp_path):
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        "\n".join(
            [
                "models:",
                "  chatgpt/gpt-5.2-codex:",
                "    timeout: 600",
                "default: chatgpt/gpt-5.2-codex",
                "",
            ]
        ),
        encoding="utf-8",
    )

    manager = ModelManager(config_path=str(config_path))
    profile = manager.get_current_model()

    assert profile is not None
    is_valid, error_message = manager.validate_model(profile)
    assert is_valid is True
    assert error_message == ""


def test_validate_copilot_model_without_api_key(tmp_path):
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        "\n".join(
            [
                "models:",
                "  github_copilot/claude-sonnet-4.5:",
                "    timeout: 600",
                "default: github_copilot/claude-sonnet-4.5",
                "",
            ]
        ),
        encoding="utf-8",
    )

    manager = ModelManager(config_path=str(config_path))
    profile = manager.get_current_model()

    assert profile is not None
    is_valid, error_message = manager.validate_model(profile)
    assert is_valid is True
    assert error_message == ""


def test_switch_model_persists_current_across_restart(tmp_path):
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        "\n".join(
            [
                "models:",
                "  openai/gpt-4o:",
                "    api_key: sk-test",
                "  chatgpt/gpt-5.2-codex:",
                "    timeout: 600",
                "default: openai/gpt-4o",
                "",
            ]
        ),
        encoding="utf-8",
    )

    manager = ModelManager(config_path=str(config_path))
    switched = manager.switch_model("chatgpt/gpt-5.2-codex")

    assert switched is not None
    assert manager.get_current_model() is not None
    assert manager.get_current_model().model_id == "chatgpt/gpt-5.2-codex"

    reloaded = ModelManager(config_path=str(config_path))
    assert reloaded.get_current_model() is not None
    assert reloaded.get_current_model().model_id == "chatgpt/gpt-5.2-codex"


def test_load_invalid_current_falls_back_to_default(tmp_path):
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        "\n".join(
            [
                "models:",
                "  openai/gpt-4o:",
                "    api_key: sk-test",
                "default: openai/gpt-4o",
                "current: chatgpt/gpt-5.2-codex",
                "",
            ]
        ),
        encoding="utf-8",
    )

    manager = ModelManager(config_path=str(config_path))
    assert manager.get_current_model() is not None
    assert manager.get_current_model().model_id == "openai/gpt-4o"
