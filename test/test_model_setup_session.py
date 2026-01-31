import types


class _FakeInputHandler:
    def __init__(self, inputs: list[str]):
        self._inputs = iter(inputs)

    async def prompt_async(self, prompt_text: str = "> ") -> str:  # noqa: ARG002
        return next(self._inputs)


async def _write_models_yaml(path, *, model_id: str = "openai/gpt-4o") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "models:",
                f"  {model_id}:",
                "    api_key: test-key",
                "default: " + model_id,
                "",
            ]
        ),
        encoding="utf-8",
    )


async def test_model_setup_auto_starts_after_model_pick(tmp_path, monkeypatch):
    import interactive
    from interactive import ModelSetupSession
    from llm import ModelManager

    config_path = tmp_path / "models.yaml"
    await _write_models_yaml(config_path, model_id="openai/gpt-4o")
    model_manager = ModelManager(config_path=str(config_path))

    async def fake_pick_model_id(_mm, title: str):  # noqa: ARG001
        return "openai/gpt-4o"

    monkeypatch.setattr(interactive, "pick_model_id", fake_pick_model_id)

    session = ModelSetupSession(model_manager=model_manager)
    session.input_handler = _FakeInputHandler(["/model"])

    ready = await session.run()
    assert ready is True


async def test_model_setup_does_not_treat_normal_text_as_model_id(tmp_path, monkeypatch):
    import interactive
    from interactive import ModelSetupSession
    from llm import ModelManager

    config_path = tmp_path / "models.yaml"
    await _write_models_yaml(config_path, model_id="anthropic/kimi-k2-5-latest")
    model_manager = ModelManager(config_path=str(config_path))

    errors: list[tuple[str, str]] = []

    def fake_print_error(message: str, title: str = "Error") -> None:
        errors.append((title, message))

    monkeypatch.setattr(interactive.terminal_ui, "print_error", fake_print_error)

    async def boom(_self, _user_input: str) -> bool:  # pragma: no cover
        raise AssertionError("_handle_model_command should not be called for normal text input")

    session = ModelSetupSession(model_manager=model_manager)
    session._handle_model_command = types.MethodType(boom, session)  # type: ignore[assignment]
    session.input_handler = _FakeInputHandler(["12 + 32 = ?", "/exit"])

    ready = await session.run()
    assert ready is False
    assert any(title == "Model Setup" for title, _ in errors)
