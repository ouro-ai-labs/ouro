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
