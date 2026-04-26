"""Enhanced input handling with auto-completion and keyboard shortcuts."""

from typing import Callable, List, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.buffer import CompletionState
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style

from utils.tui.command_registry import CommandRegistry
from utils.tui.slash_autocomplete import SlashAutocompleteEngine, SlashSuggestion
from utils.tui.theme import Theme


def _relative_luminance(color: str) -> float | None:
    """Return WCAG relative luminance for #RRGGBB colors."""
    if not (len(color) == 7 and color.startswith("#")):
        return None

    try:
        r = int(color[1:3], 16) / 255.0
        g = int(color[3:5], 16) / 255.0
        b = int(color[5:7], 16) / 255.0
    except ValueError:
        return None

    def _linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    rl = _linear(r)
    gl = _linear(g)
    bl = _linear(b)
    return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl


def _best_contrast_text(background: str) -> str:
    """Pick black/white text with best contrast for a background color."""
    luminance = _relative_luminance(background)
    if luminance is None:
        return "#FFFFFF"

    contrast_white = (1.0 + 0.05) / (luminance + 0.05)
    contrast_black = (luminance + 0.05) / 0.05
    return "#FFFFFF" if contrast_white >= contrast_black else "#000000"


def _normalize_command_tree(
    commands: list[str] | None,
    command_subcommands: dict[str, dict[str, str]] | None,
) -> tuple[list[str], dict[str, dict[str, str]]]:
    top_commands: list[str] = []
    seen_top: set[str] = set()
    subcommands: dict[str, dict[str, str]] = {}

    def _add_top(cmd: str) -> None:
        if cmd in seen_top:
            return
        seen_top.add(cmd)
        top_commands.append(cmd)

    for raw in commands or []:
        parts = [p for p in raw.strip().split(" ") if p]
        if not parts:
            continue
        top = parts[0]
        _add_top(top)
        if len(parts) > 1:
            sub = " ".join(parts[1:])
            subcommands.setdefault(top, {}).setdefault(sub, "")

    for top, subs in (command_subcommands or {}).items():
        _add_top(top)
        subcommands.setdefault(top, {}).update(subs)

    return top_commands, subcommands


class CommandCompleter(Completer):
    """Auto-completer for slash commands."""

    def __init__(
        self,
        commands: Optional[List[str]] = None,
        help_texts: Optional[dict[str, str]] = None,
        command_subcommands: Optional[dict[str, dict[str, str]]] = None,
        display_texts: Optional[dict[str, str]] = None,
    ):
        """Initialize completer.

        Args:
            commands: List of available commands (without leading /)
            help_texts: Optional help text per command (same keys as commands)
            command_subcommands: Optional mapping like {"model": {"edit": "..."}}.
            display_texts: Optional display text (with leading / and args hints).
        """
        default_commands = [
            "help",
            "reset",
            "stats",
            "resume",
            "theme",
            "verbose",
            "compact",
            "model",
            "exit",
            "quit",
        ]
        self.commands, self.command_subcommands = _normalize_command_tree(
            commands or default_commands,
            command_subcommands,
        )

        default_help_texts = {
            "help": "Show available commands",
            "reset": "Clear conversation memory",
            "stats": "Show token/memory stats",
            "resume": "List and resume a previous session",
            "theme": "Switch color theme",
            "verbose": "Toggle verbose output",
            "compact": "Compress conversation memory",
            "model": "Manage models",
            "model edit": "Edit `.ouro/models.yaml` (auto-reload on save)",
            "exit": "Exit interactive mode",
            "quit": "Same as /exit",
        }

        merged_help_texts = {**default_help_texts, **(help_texts or {})}
        for base, subs in self.command_subcommands.items():
            for sub, sub_help in subs.items():
                if sub_help:
                    merged_help_texts[f"{base} {sub}"] = sub_help

        self.help_texts = merged_help_texts
        self.display_texts = display_texts or {}
        self.engine = SlashAutocompleteEngine(
            self.commands,
            self.command_subcommands,
            help_texts=self.help_texts,
            display_texts=self.display_texts,
        )

    def get_completions(
        self,
        document: Document,
        complete_event: CompleteEvent | None,
    ):
        """Get completions for the current input.

        Args:
            document: Current document
            complete_event: Completion event

        Yields:
            Completion objects
        """
        suggestions = self.get_suggestions(document.text_before_cursor)
        for suggestion in suggestions:
            yield self._to_completion(suggestion)

    def get_suggestions(self, text_before_cursor: str) -> list[SlashSuggestion]:
        """Return ordered slash suggestions for UI rendering and enter resolution."""
        return self.engine.suggest(text_before_cursor)

    def get_enter_completion(
        self,
        document: Document,
        complete_state: CompletionState | None,
    ) -> Completion | None:
        """Resolve completion to apply when Enter is pressed in slash context."""
        suggestions = self.get_suggestions(document.text_before_cursor)
        if not suggestions:
            return None

        if complete_state is not None and complete_state.current_completion is not None:
            return complete_state.current_completion

        return self._to_completion(suggestions[0])

    def _to_completion(self, suggestion: SlashSuggestion) -> Completion:
        return Completion(
            suggestion.insert_text,
            start_position=-len(suggestion.replace_text),
            display=suggestion.display,
            display_meta=suggestion.help_text,
        )


class InputHandler:
    """Enhanced input handler with completion, history, and shortcuts."""

    def __init__(
        self,
        history_file: Optional[str] = None,
        commands: Optional[List[str]] = None,
        command_help: Optional[dict[str, str]] = None,
        command_subcommands: Optional[dict[str, dict[str, str]]] = None,
        command_registry: CommandRegistry | None = None,
    ):
        """Initialize input handler.

        Args:
            history_file: Path to history file (None for in-memory)
            commands: List of available commands
        """
        # Set up history
        history = FileHistory(history_file) if history_file else InMemoryHistory()

        display_texts: dict[str, str] | None = None
        if command_registry is not None:
            commands = [c.name for c in command_registry.commands]
            command_help = command_registry.to_help_map()
            command_subcommands = command_registry.to_subcommand_map()
            display_texts = command_registry.to_display_map()

        # Set up completer
        self.completer = CommandCompleter(
            commands,
            help_texts=command_help,
            command_subcommands=command_subcommands,
            display_texts=display_texts,
        )

        # Set up key bindings
        self.key_bindings = self._create_key_bindings()

        # Callback handlers
        self._on_clear_screen: Optional[Callable[[], None]] = None
        self._on_toggle_thinking: Optional[Callable[[], None]] = None
        self._on_show_stats: Optional[Callable[[], None]] = None

        def bottom_toolbar() -> str | list[tuple[str, str]]:
            buffer = self.session.default_buffer

            # Avoid duplicate visual noise when the popup completion menu is visible.
            if buffer.complete_state is not None and buffer.complete_state.completions:
                return ""

            suggestions = self._get_command_suggestions(buffer.text)
            if not suggestions:
                return ""

            fragments: list[tuple[str, str]] = []
            fragments.append(("class:toolbar.hint", "Commands: "))
            for i, (display, help_text) in enumerate(suggestions[:5]):
                if i:
                    fragments.append(("class:toolbar.hint", "  "))
                fragments.append(("class:toolbar.cmd", display))
                if help_text:
                    fragments.append(("class:toolbar.hint", f" — {help_text}"))
            return fragments

        # Create prompt session with auto-complete while typing.
        # The completer itself is responsible for returning results only for slash commands.
        self.session: PromptSession = PromptSession(
            history=history,
            completer=self.completer,
            key_bindings=self.key_bindings,
            complete_while_typing=True,
            enable_history_search=True,
            bottom_toolbar=bottom_toolbar,
        )

        def _on_text_insert(_buffer: object) -> None:
            # Best-effort: show completion menu right after typing "/" at the beginning.
            buf = self.session.default_buffer
            if buf.text == "/" and buf.cursor_position == 1:
                buf.start_completion(
                    select_first=False,
                    complete_event=CompleteEvent(text_inserted=True),
                )

        self.session.default_buffer.on_text_insert += _on_text_insert

        def _on_text_changed(_buffer: object) -> None:
            # Codex-style: when the input starts with "/", keep the completion menu in sync
            # with every keystroke. (Some terminals don't refresh completion state reliably
            # unless we explicitly trigger it.)
            buf = self.session.default_buffer
            if buf.text.startswith("/"):
                buf.start_completion(
                    select_first=False,
                    complete_event=CompleteEvent(text_inserted=True),
                )
            else:
                buf.cancel_completion()

        self.session.default_buffer.on_text_changed += _on_text_changed

    def _get_command_suggestions(self, text: str) -> list[tuple[str, str]]:
        return [
            (suggestion.display, suggestion.help_text)
            for suggestion in self.completer.get_suggestions(text)
        ]

    def _create_key_bindings(self) -> KeyBindings:
        """Create custom key bindings.

        Returns:
            KeyBindings instance
        """
        kb = KeyBindings()

        @kb.add("/", eager=True)
        def slash_command(event: KeyPressEvent) -> None:
            """Insert '/' and, when starting a command, show suggestions immediately."""
            buffer = event.current_buffer
            at_start = buffer.text == "" and buffer.cursor_position == 0
            buffer.insert_text("/")
            if at_start:
                buffer.start_completion(select_first=False)

        @kb.add("enter", eager=True)
        def accept_or_submit_slash(event: KeyPressEvent) -> None:
            """Codex-style Enter: accept best slash completion, then submit."""
            buffer = event.current_buffer
            completion = self.completer.get_enter_completion(buffer.document, buffer.complete_state)
            if completion is not None:
                buffer.apply_completion(completion)
            buffer.validate_and_handle()

        @kb.add(Keys.ControlL)
        def clear_screen(event: KeyPressEvent) -> None:
            """Clear the screen."""
            event.app.renderer.clear()
            if self._on_clear_screen:
                self._on_clear_screen()

        @kb.add(Keys.ControlT)
        def toggle_thinking(event: KeyPressEvent) -> None:
            """Toggle thinking display."""
            if self._on_toggle_thinking:
                self._on_toggle_thinking()

        @kb.add(Keys.ControlS)
        def show_stats(event: KeyPressEvent) -> None:
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
        current_fg = _best_contrast_text(colors.primary)

        # Start from shared theme defaults so prompt_toolkit styling stays consistent.
        style_dict = Theme.get_prompt_toolkit_style().copy()
        style_dict.update(
            {
                "prompt": f"{colors.user_input} bold",
                "": colors.text_primary,
                "completion-menu": f"bg:{colors.bg_secondary} {colors.text_primary}",
                "completion-menu.completion": f"bg:{colors.bg_secondary} {colors.text_primary}",
                "completion-menu.completion.current": f"bg:{colors.primary} {current_fg} bold",
                "completion-menu.meta.completion": f"bg:{colors.bg_secondary} {colors.text_secondary}",
                "completion-menu.meta.completion.current": f"bg:{colors.primary} {current_fg}",
                "toolbar.hint": colors.text_muted,
                "toolbar.cmd": f"{colors.primary} bold",
                "scrollbar.background": colors.bg_secondary,
                "scrollbar.button": colors.text_muted,
            }
        )
        return Style.from_dict(style_dict)

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
