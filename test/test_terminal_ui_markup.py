from io import StringIO

from rich.console import Console

from ouro.interfaces.tui import terminal_ui


def test_print_tool_call_escapes_markup_in_dynamic_fields(monkeypatch):
    output = StringIO()
    monkeypatch.setattr(
        terminal_ui,
        "console",
        Console(file=output, force_terminal=True, width=120),
    )

    terminal_ui.print_tool_call(
        "[agent-2] shell",
        {
            "[bad-key]": "literal closing tag [/{colors.text_secondary}]",
            "command": "printf '[not markup]'",
        },
    )

    rendered = output.getvalue()
    assert "Tool:" in rendered
    assert "literal closing tag" in rendered


def test_print_tool_blocked_escapes_markup_in_dynamic_fields(monkeypatch):
    output = StringIO()
    monkeypatch.setattr(
        terminal_ui,
        "console",
        Console(file=output, force_terminal=True, width=120),
    )

    terminal_ui.print_tool_blocked(
        "[agent-2] shell",
        {"command": "printf '[not markup]'"},
        "blocked because [/{colors.warning}] should be literal",
    )

    rendered = output.getvalue()
    assert "Blocked:" in rendered
    assert "should be literal" in rendered
