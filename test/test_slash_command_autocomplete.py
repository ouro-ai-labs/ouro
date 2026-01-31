from prompt_toolkit.document import Document

from utils.tui.input_handler import CommandCompleter, InputHandler


def _meta_text(completion) -> str:
    if completion.display_meta is None:
        return ""
    fragments = list(completion.display_meta)
    return "".join(text for _, text in fragments)


def test_command_completer_no_results_without_slash() -> None:
    completer = CommandCompleter(commands=["help", "clear"])
    doc = Document(text="hello", cursor_position=5)
    assert list(completer.get_completions(doc, None)) == []


def test_command_completer_slash_lists_commands_with_meta() -> None:
    completer = CommandCompleter(commands=["help", "clear"])
    doc = Document(text="/", cursor_position=1)
    completions = list(completer.get_completions(doc, None))

    assert [c.text for c in completions] == ["help", "clear"]
    assert _meta_text(completions[0]) == "Show available commands"
    assert _meta_text(completions[1]) == "Clear conversation memory"


def test_command_completer_prefix_filters_and_start_position() -> None:
    completer = CommandCompleter(commands=["help", "clear"])
    doc = Document(text="/he", cursor_position=3)
    completions = list(completer.get_completions(doc, None))

    assert [c.text for c in completions] == ["help"]
    assert completions[0].start_position == -2


def test_input_handler_completes_while_typing() -> None:
    handler = InputHandler(history_file=None, commands=["help", "clear"])
    assert handler.session.complete_while_typing is True


def test_input_handler_slash_key_triggers_completion_binding() -> None:
    handler = InputHandler(history_file=None, commands=["help", "clear"])
    slash_bindings = [b for b in handler.key_bindings.bindings if any(k == "/" for k in b.keys)]
    assert len(slash_bindings) == 1
    assert slash_bindings[0].eager()


def test_input_handler_command_suggestions() -> None:
    handler = InputHandler(history_file=None, commands=["help", "clear"])
    assert handler._get_command_suggestions("hello") == []
    assert handler._get_command_suggestions("/") == [
        ("/help", "Show available commands"),
        ("/clear", "Clear conversation memory"),
    ]
    assert handler._get_command_suggestions("/he") == [("/help", "Show available commands")]


def test_subcommand_completion_and_suggestions() -> None:
    handler = InputHandler(
        history_file=None,
        commands=["model", "help"],
        command_subcommands={"model": {"edit": "Open config"}},
    )
    assert handler._get_command_suggestions("/model ") == [("/model edit", "Open config")]

    completer = handler.completer
    doc = Document(text="/model e", cursor_position=len("/model e"))
    completions = list(completer.get_completions(doc, None))
    assert [c.text for c in completions] == ["edit"]
    assert _meta_text(completions[0]) == "Open config"
