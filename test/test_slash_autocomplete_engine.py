from types import SimpleNamespace

from prompt_toolkit.document import Document

from utils.tui.input_handler import CommandCompleter
from utils.tui.slash_autocomplete import SlashAutocompleteEngine


def test_engine_returns_no_suggestions_without_slash() -> None:
    engine = SlashAutocompleteEngine(commands=["help"], command_subcommands={})
    assert engine.suggest("hello") == []


def test_engine_fuzzy_command_matching_orders_best_first() -> None:
    engine = SlashAutocompleteEngine(
        commands=["help", "reset", "resume", "model"],
        command_subcommands={},
    )

    suggestions = engine.suggest("/rs")
    assert [s.insert_text for s in suggestions] == ["reset", "resume"]


def test_engine_fuzzy_subcommand_matching() -> None:
    engine = SlashAutocompleteEngine(
        commands=["model"],
        command_subcommands={"model": {"edit": "Edit config", "list": "List models"}},
    )

    suggestions = engine.suggest("/model edt")
    assert [s.insert_text for s in suggestions] == ["edit"]


def test_completer_enter_uses_top_suggestion_when_none_selected() -> None:
    completer = CommandCompleter(commands=["help", "model"])
    doc = Document(text="/mod", cursor_position=len("/mod"))

    completion = completer.get_enter_completion(doc, complete_state=None)

    assert completion is not None
    assert completion.text == "model"
    assert completion.start_position == -3


def test_completer_enter_prefers_currently_selected_completion() -> None:
    completer = CommandCompleter(commands=["reset", "resume"])
    doc = Document(text="/rs", cursor_position=3)

    completions = list(completer.get_completions(doc, None))
    selected = completions[1]

    completion = completer.get_enter_completion(
        doc,
        complete_state=SimpleNamespace(current_completion=selected),
    )

    assert completion is selected
