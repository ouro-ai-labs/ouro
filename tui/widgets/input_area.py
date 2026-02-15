"""Input area widget with multi-line support and completions."""

from pathlib import Path
from typing import List

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option


class InputArea(Widget):
    """Multi-line input area with @ file completion and / command completion."""

    DEFAULT_CSS = """
    InputArea {
        height: auto;
        min-height: 3;
        max-height: 12;
        background: $surface;
        border-top: solid $primary-darken-1;
        padding: 0;
    }

    InputArea > #input-container {
        height: auto;
        padding: 0 2;
    }

    InputArea > #input-container > Input {
        height: auto;
        min-height: 1;
        border: none;
        background: $surface;
        padding: 0 1;
        width: 100%;
    }

    InputArea > #input-container > Input:focus {
        border: none;
    }

    InputArea > #input-hint {
        display: none;
    }

    InputArea > #completion-container {
        height: auto;
        max-height: 8;
        display: none;
        padding: 0 2;
    }

    InputArea > #completion-container.visible {
        display: block;
    }

    InputArea #completion-list {
        height: auto;
        max-height: 6;
        background: $surface-darken-1;
        border: solid $primary-darken-2;
    }

    InputArea #completion-list > .option-list--option {
        padding: 0 1;
    }
    """

    # Available commands
    COMMANDS = [
        ("/help", "Show available commands"),
        ("/clear", "Clear conversation memory"),
        ("/reset", "Clear conversation memory"),
        ("/stats", "Show memory statistics"),
        ("/compact", "Compress conversation memory"),
        ("/model", "Show or switch models"),
        ("/verbose", "Toggle thinking display"),
        ("/resume", "Resume a saved session"),
        ("/login", "Login to OAuth provider"),
        ("/logout", "Logout from OAuth provider"),
        ("/exit", "Exit ouro"),
        ("/quit", "Exit ouro"),
    ]

    show_completions: reactive[bool] = reactive(False)
    completion_items: reactive[List[tuple]] = reactive([])

    class Submitted(Message, bubble=True):
        """Message sent when user submits input."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    class CommandSubmitted(Message, bubble=True):
        """Message sent when user submits a command."""

        def __init__(self, command: str, args: List[str]) -> None:
            super().__init__()
            self.command = command
            self.args = args

    def __init__(
        self,
        placeholder: str = "Type message... (@file, /cmd)",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.placeholder = placeholder
        self._completion_prefix = ""
        self._completion_type = ""  # "file" or "command"
        # Input history
        self._history: List[str] = []
        self._history_index = -1  # -1 means not browsing history
        self._saved_input = ""  # saves current input when entering history

    def compose(self) -> ComposeResult:
        with Container(id="completion-container"):
            yield OptionList(id="completion-list")
        with Container(id="input-container"):
            yield Input(placeholder=self.placeholder, id="main-input")
        yield Static("> Type message... (@file, /cmd)  [?]", id="input-hint")

    def on_mount(self) -> None:
        """Focus the input on mount."""
        self.query_one("#main-input", Input).focus()

    @on(Input.Changed, "#main-input")
    def handle_input_change(self, event: Input.Changed) -> None:
        """Handle input changes for completion triggers."""
        value = event.value

        # Check for @ file completion
        at_pos = value.rfind("@")
        if at_pos >= 0 and (at_pos == 0 or value[at_pos - 1] == " "):
            prefix = value[at_pos + 1 :]
            if " " not in prefix:  # Still typing the path
                self._show_file_completions(prefix)
                return

        # Check for / command completion
        if value.startswith("/") and " " not in value:
            self._show_command_completions(value)
            return

        # Hide completions
        self._hide_completions()

    @on(Input.Submitted, "#main-input")
    def handle_input_submit(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        value = event.value.strip()
        if not value:
            return

        # Record in history
        if not self._history or self._history[-1] != value:
            self._history.append(value)
        self._history_index = -1
        self._saved_input = ""

        # Clear input
        self.query_one("#main-input", Input).value = ""
        self._hide_completions()

        # Check if it's a command
        if value.startswith("/"):
            parts = value.split()
            command = parts[0].lower()
            args = parts[1:] if len(parts) > 1 else []
            self.post_message(self.CommandSubmitted(command, args))
        else:
            self.post_message(self.Submitted(value))

    def on_key(self, event) -> None:
        """Handle key events for history navigation and tab completion."""
        if event.key == "tab":
            if self.show_completions:
                # Accept highlighted completion
                completion_list = self.query_one("#completion-list", OptionList)
                idx = completion_list.highlighted
                if idx is not None:
                    option = completion_list.get_option_at_index(idx)
                    if option and option.id:
                        self._apply_completion(option.id)
                event.prevent_default()
                event.stop()
            return
        if event.key == "up":
            if self.show_completions:
                # Let OptionList handle navigation
                return
            if not self._history:
                event.prevent_default()
                event.stop()
                return
            if self._history_index == -1:
                # Entering history mode — save current input
                self._saved_input = self.query_one("#main-input", Input).value
                self._history_index = len(self._history) - 1
            elif self._history_index > 0:
                self._history_index -= 1
            else:
                event.prevent_default()
                event.stop()
                return
            self.query_one("#main-input", Input).value = self._history[self._history_index]
            event.prevent_default()
            event.stop()
        elif event.key == "down":
            if self.show_completions:
                return
            if self._history_index == -1:
                return
            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                self.query_one("#main-input", Input).value = self._history[self._history_index]
            else:
                # Back to current input
                self._history_index = -1
                self.query_one("#main-input", Input).value = self._saved_input
            event.prevent_default()
            event.stop()

    @on(OptionList.OptionSelected, "#completion-list")
    def handle_completion_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle completion selection."""
        selected = event.option
        if selected and selected.id:
            self._apply_completion(selected.id)

    def _show_file_completions(self, prefix: str) -> None:
        """Show file path completions."""
        self._completion_prefix = prefix
        self._completion_type = "file"

        # Get file completions
        completions = self._get_file_completions(prefix)
        if not completions:
            self._hide_completions()
            return

        # Update completion list
        completion_list = self.query_one("#completion-list", OptionList)
        completion_list.clear_options()
        for path, is_dir in completions[:10]:  # Limit to 10
            display = f"{path}/" if is_dir else path
            option = Option(display, id=path)
            completion_list.add_option(option)

        # Show completion container
        container = self.query_one("#completion-container")
        container.add_class("visible")
        self.show_completions = True

    def _show_command_completions(self, prefix: str) -> None:
        """Show command completions."""
        self._completion_prefix = prefix
        self._completion_type = "command"

        # Filter commands
        matches = [
            (cmd, desc)
            for cmd, desc in self.COMMANDS
            if cmd.startswith(prefix.lower()) or prefix == "/"
        ]
        if not matches:
            self._hide_completions()
            return

        # Update completion list
        completion_list = self.query_one("#completion-list", OptionList)
        completion_list.clear_options()
        for cmd, desc in matches:
            option = Option(f"{cmd}  {desc}", id=cmd)
            completion_list.add_option(option)

        # Show completion container
        container = self.query_one("#completion-container")
        container.add_class("visible")
        self.show_completions = True

    def _hide_completions(self) -> None:
        """Hide completion popup."""
        container = self.query_one("#completion-container")
        container.remove_class("visible")
        self.show_completions = False
        self._completion_prefix = ""
        self._completion_type = ""

    def _apply_completion(self, completion: str) -> None:
        """Apply the selected completion to input."""
        input_widget = self.query_one("#main-input", Input)
        value = input_widget.value

        if self._completion_type == "file":
            # Find the @ and replace from there
            at_pos = value.rfind("@")
            if at_pos >= 0:
                new_value = value[: at_pos + 1] + completion + " "
                input_widget.value = new_value
        elif self._completion_type == "command":
            # Replace the whole command
            input_widget.value = completion + " "

        self._hide_completions()
        input_widget.focus()

    def _get_file_completions(self, prefix: str, max_results: int = 20) -> List[tuple]:
        """Get file path completions based on prefix.

        Returns list of (path, is_dir) tuples.
        """
        completions = []
        cwd = Path.cwd()

        try:
            if not prefix:
                # Show current directory contents
                search_dir = cwd
                search_prefix = ""
            elif "/" in prefix:
                # Partial path - search in parent directory
                parts = prefix.rsplit("/", 1)
                parent = parts[0]
                search_prefix = parts[1].lower()
                search_dir = cwd / parent if parent else cwd
            else:
                # Just a filename prefix
                search_dir = cwd
                search_prefix = prefix.lower()

            if not search_dir.exists():
                return []

            # List directory contents
            for entry in search_dir.iterdir():
                name = entry.name
                if name.startswith("."):  # Skip hidden files
                    continue
                if search_prefix and not name.lower().startswith(search_prefix):
                    continue

                # Build relative path from cwd
                try:
                    rel_path = entry.relative_to(cwd)
                    completions.append((str(rel_path), entry.is_dir()))
                except ValueError:
                    completions.append((str(entry), entry.is_dir()))

                if len(completions) >= max_results:
                    break

            # Sort: directories first, then by name
            completions.sort(key=lambda x: (not x[1], x[0].lower()))

        except Exception:
            pass

        return completions

    def focus_input(self) -> None:
        """Focus the input widget."""
        self.query_one("#main-input", Input).focus()
