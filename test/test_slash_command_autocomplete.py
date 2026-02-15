from types import SimpleNamespace

from prompt_toolkit.document import Document

from utils.tui.input_handler import CommandCompleter, InputHandler, _best_contrast_text


def _meta_text(completion) -> str:
    if completion.display_meta is None:
        return ""
    fragments = list(completion.display_meta)
    return "".join(text for _, text in fragments)


def test_command_completer_no_results_without_slash() -> None:
    completer = CommandCompleter(commands=["help", "reset"])
    doc = Document(text="hello", cursor_position=5)
    assert list(completer.get_completions(doc, None)) == []


def test_command_completer_slash_lists_commands_with_meta() -> None:
    completer = CommandCompleter(commands=["help", "reset"])
    doc = Document(text="/", cursor_position=1)
    completions = list(completer.get_completions(doc, None))

    assert [c.text for c in completions] == ["help", "reset"]
    assert _meta_text(completions[0]) == "Show available commands"
    assert _meta_text(completions[1]) == "Clear conversation memory"


def test_command_completer_prefix_filters_and_start_position() -> None:
    completer = CommandCompleter(commands=["help", "reset"])
    doc = Document(text="/he", cursor_position=3)
    completions = list(completer.get_completions(doc, None))

    assert [c.text for c in completions] == ["help"]
    assert completions[0].start_position == -2


def test_input_handler_completes_while_typing() -> None:
    handler = InputHandler(history_file=None, commands=["help", "reset"])
    assert handler.session.complete_while_typing is True


def test_input_handler_slash_key_triggers_completion_binding() -> None:
    handler = InputHandler(history_file=None, commands=["help", "reset"])
    slash_bindings = [b for b in handler.key_bindings.bindings if any(k == "/" for k in b.keys)]
    assert len(slash_bindings) == 1
    assert slash_bindings[0].eager()


def test_slash_binding_does_not_select_first_completion() -> None:
    handler = InputHandler(history_file=None, commands=["help", "reset"])
    slash_bindings = [b for b in handler.key_bindings.bindings if any(k == "/" for k in b.keys)]
    binding = slash_bindings[0]

    class DummyBuffer:
        def __init__(self) -> None:
            self.text = ""
            self.cursor_position = 0
            self.select_first_calls: list[bool] = []

        def insert_text(self, text: str) -> None:
            self.text += text
            self.cursor_position += len(text)

        def start_completion(self, *, select_first: bool) -> None:
            self.select_first_calls.append(select_first)

    buffer = DummyBuffer()
    event = SimpleNamespace(current_buffer=buffer)

    binding.handler(event)

    assert buffer.text == "/"
    assert buffer.select_first_calls == [False]


def test_enter_completion_is_none_for_non_slash_input() -> None:
    completer = CommandCompleter(commands=["help", "reset"])
    doc = Document(text="hello", cursor_position=5)

    assert completer.get_enter_completion(doc, None) is None


def test_input_handler_command_suggestions() -> None:
    handler = InputHandler(history_file=None, commands=["help", "reset"])
    assert handler._get_command_suggestions("hello") == []
    assert handler._get_command_suggestions("/") == [
        ("/help", "Show available commands"),
        ("/reset", "Clear conversation memory"),
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


def test_best_contrast_text_prefers_white_on_blue() -> None:
    assert _best_contrast_text("#0969DA") == "#FFFFFF"


def test_best_contrast_text_prefers_black_on_bright_cyan() -> None:
    assert _best_contrast_text("#00D9FF") == "#000000"
