"""Help screen modal."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class HelpScreen(ModalScreen[None]):
    """Modal screen showing keyboard shortcuts and commands."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("f1", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }

    HelpScreen > #help-container {
        width: 60;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: double $primary;
        padding: 1 2;
    }

    HelpScreen .help-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    HelpScreen .help-section-title {
        color: $secondary;
        text-style: bold;
        margin-top: 1;
    }

    HelpScreen .help-row {
        layout: horizontal;
        height: 1;
    }

    HelpScreen .help-key {
        width: 20;
        color: $warning;
    }

    HelpScreen .help-desc {
        width: 1fr;
        color: $text;
    }

    HelpScreen #close-button {
        margin-top: 1;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="help-container"):
            yield Static("\u25c9 ouro Help", classes="help-title")

            # Keyboard shortcuts section
            yield Static("Keyboard Shortcuts", classes="help-section-title")

            shortcuts = [
                ("Enter", "Send message"),
                ("Ctrl+D", "Exit ouro"),
                ("Ctrl+L", "Clear screen"),
                ("Escape", "Cancel / Close"),
                ("F1 / ?", "Show this help"),
                ("\u2191 / \u2193", "Navigate history / completions"),
                ("Tab", "Accept completion"),
            ]

            for key, desc in shortcuts:
                with Container(classes="help-row"):
                    yield Static(key, classes="help-key")
                    yield Static(desc, classes="help-desc")

            # Commands section
            yield Static("Commands", classes="help-section-title")

            commands = [
                ("/help", "Show available commands"),
                ("/clear, /reset", "Clear conversation memory"),
                ("/stats", "Show memory statistics"),
                ("/compact", "Compress conversation memory"),
                ("/model [id]", "Show or switch models"),
                ("/verbose", "Toggle thinking display"),
                ("/resume <id>", "Resume a saved session"),
                ("/login [provider]", "Login to OAuth provider"),
                ("/logout [provider]", "Logout from OAuth provider"),
                ("/exit", "Exit ouro"),
            ]

            for cmd, desc in commands:
                with Container(classes="help-row"):
                    yield Static(cmd, classes="help-key")
                    yield Static(desc, classes="help-desc")

            # Input hints section
            yield Static("Input Hints", classes="help-section-title")

            hints = [
                ("@filename", "File path completion"),
                ("/cmd", "Command completion"),
            ]

            for hint, desc in hints:
                with Container(classes="help-row"):
                    yield Static(hint, classes="help-key")
                    yield Static(desc, classes="help-desc")

            yield Button("Close (Esc)", id="close-button", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle close button."""
        if event.button.id == "close-button":
            self.dismiss()

    def action_dismiss(self) -> None:
        """Dismiss the modal."""
        self.dismiss()
