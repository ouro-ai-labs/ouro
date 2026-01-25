"""Enhanced input handling with auto-completion and keyboard shortcuts."""

from typing import Callable, List, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.filters import Condition
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style

from utils.tui.theme import Theme


class CommandCompleter(Completer):
    """Auto-completer for slash commands and file paths."""

    def __init__(self, commands: Optional[List[str]] = None):
        """Initialize completer.

        Args:
            commands: List of available commands (without leading /)
        """
        self.commands = commands or [
            "help",
            "clear",
            "stats",
            "history",
            "dump-memory",
            "theme",
            "verbose",
            "compact",
            "exit",
            "quit",
        ]

    def get_completions(self, document, complete_event):
        """Get completions for the current input.

        Args:
            document: Current document
            complete_event: Completion event

        Yields:
            Completion objects
        """
        text = document.text_before_cursor

        # Complete commands starting with /
        if text.startswith("/"):
            cmd_text = text[1:]  # Remove leading /
            # Sort commands by relevance (exact prefix match first)
            matching_commands = [cmd for cmd in self.commands if cmd.startswith(cmd_text)]
            for cmd in matching_commands:
                yield Completion(
                    cmd,
                    start_position=-len(cmd_text),
                    display=f"/{cmd}",
                    display_meta=self._get_command_help(cmd),
                )

    def _get_command_help(self, cmd: str) -> str:
        """Get help text for a command.

        Args:
            cmd: Command name

        Returns:
            Help text
        """
        help_texts = {
            "help": "Show available commands",
            "clear": "Clear conversation memory",
            "stats": "Show token/memory stats",
            "history": "List saved sessions",
            "dump-memory": "Export session to JSON",
            "theme": "Switch color theme",
            "verbose": "Toggle verbose output",
            "compact": "Toggle compact mode",
            "exit": "Exit interactive mode",
            "quit": "Same as /exit",
        }
        return help_texts.get(cmd, "")


class InputHandler:
    """Enhanced input handler with completion, history, and shortcuts."""

    def __init__(
        self,
        history_file: Optional[str] = None,
        commands: Optional[List[str]] = None,
    ):
        """Initialize input handler.

        Args:
            history_file: Path to history file (None for in-memory)
            commands: List of available commands
        """
        # Set up history
        history = FileHistory(history_file) if history_file else InMemoryHistory()

        # Set up completer
        self.completer = CommandCompleter(commands)

        # Set up key bindings
        self.key_bindings = self._create_key_bindings()

        # Callback handlers
        self._on_clear_screen: Optional[Callable[[], None]] = None
        self._on_toggle_thinking: Optional[Callable[[], None]] = None
        self._on_show_stats: Optional[Callable[[], None]] = None

        # Create condition for auto-complete: only when input starts with '/'
        @Condition
        def is_command_input() -> bool:
            app = self.session.app
            if app is None:
                return False
            text = app.current_buffer.text
            return text.startswith("/")

        self._is_command_input = is_command_input

        # Create prompt session with conditional auto-complete
        self.session: PromptSession = PromptSession(
            history=history,
            completer=self.completer,
            key_bindings=self.key_bindings,
            complete_while_typing=is_command_input,  # Auto-complete only for commands
            enable_history_search=True,
        )

    def _create_key_bindings(self) -> KeyBindings:
        """Create custom key bindings.

        Returns:
            KeyBindings instance
        """
        kb = KeyBindings()

        @kb.add(Keys.ControlL)
        def clear_screen(event):
            """Clear the screen."""
            event.app.renderer.clear()
            if self._on_clear_screen:
                self._on_clear_screen()

        @kb.add(Keys.ControlT)
        def toggle_thinking(event):
            """Toggle thinking display."""
            if self._on_toggle_thinking:
                self._on_toggle_thinking()

        @kb.add(Keys.ControlS)
        def show_stats(event):
            """Show quick stats."""
            if self._on_show_stats:
                self._on_show_stats()

        return kb

    def set_callbacks(
        self,
        on_clear_screen: Optional[Callable[[], None]] = None,
        on_toggle_thinking: Optional[Callable[[], None]] = None,
        on_show_stats: Optional[Callable[[], None]] = None,
    ) -> None:
        """Set callback handlers for keyboard shortcuts.

        Args:
            on_clear_screen: Callback for Ctrl+L
            on_toggle_thinking: Callback for Ctrl+T
            on_show_stats: Callback for Ctrl+S
        """
        self._on_clear_screen = on_clear_screen
        self._on_toggle_thinking = on_toggle_thinking
        self._on_show_stats = on_show_stats

    def get_style(self) -> Style:
        """Get prompt_toolkit style based on current theme.

        Returns:
            Style instance
        """
        colors = Theme.get_colors()
        return Style.from_dict(
            {
                "prompt": f"{colors.user_input} bold",
                "": colors.text_primary,
                "completion-menu": f"bg:{colors.bg_secondary} {colors.text_primary}",
                "completion-menu.completion": f"bg:{colors.bg_secondary} {colors.text_primary}",
                "completion-menu.completion.current": f"bg:{colors.primary} #000000",
                "scrollbar.background": colors.bg_secondary,
                "scrollbar.button": colors.text_muted,
            }
        )

    async def prompt_async(self, prompt_text: str = "> ") -> str:
        """Get input from user asynchronously.

        Args:
            prompt_text: Prompt text to display

        Returns:
            User input string
        """
        style = self.get_style()

        result = await self.session.prompt_async(
            [("class:prompt", prompt_text)],
            style=style,
        )
        return result.strip()

    def prompt(self, prompt_text: str = "> ") -> str:
        """Get input from user synchronously.

        Args:
            prompt_text: Prompt text to display

        Returns:
            User input string
        """
        style = self.get_style()

        result = self.session.prompt(
            [("class:prompt", prompt_text)],
            style=style,
        )
        return result.strip()
