"""Enhanced input handling with auto-completion and keyboard shortcuts."""

import os
from typing import Callable, List, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style

from utils.tui.command_registry import CommandRegistry
from utils.tui.theme import Theme

_DEFAULT_HELP_TEXTS: dict[str, str] = {
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

    _cache_key: str | None
    _cache_completions: list[Completion]

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
        self.help_texts = help_texts or {}
        self.display_texts = display_texts or {}

        self._cache_key = None
        self._cache_completions = []

    def get_completions(self, document, complete_event):
        """Get completions for the current input.

        Args:
            document: Current document
            complete_event: Completion event

        Yields:
            Completion objects
        """
        text = document.text_before_cursor

        # Cache by full text-before-cursor; prompt_toolkit may call the completer
        # multiple times per render.
        if text == self._cache_key:
            for c in self._cache_completions:
                yield c
            return

        completions: list[Completion] = []

        # Complete commands starting with /
        if text.startswith("/"):
            cmd_text = text[1:]  # Remove leading /
            if " " in cmd_text:
                base, _, rest = cmd_text.partition(" ")
                if base in self.command_subcommands and " " not in rest:
                    matching = [
                        sub for sub in self.command_subcommands[base] if sub.startswith(rest)
                    ]
                    for sub in matching:
                        key = f"{base} {sub}".strip()
                        display = self.display_texts.get(key, f"/{base} {sub}")
                        completions.append(
                            Completion(
                                sub,
                                start_position=-len(rest),
                                display=display,
                                display_meta=self._get_command_help(key),
                            )
                        )

            else:
                matching_commands = [cmd for cmd in self.commands if cmd.startswith(cmd_text)]
                completions.extend(
                    [
                        Completion(
                            cmd,
                            start_position=-len(cmd_text),
                            display=self.display_texts.get(cmd, f"/{cmd}"),
                            display_meta=self._get_command_help(cmd),
                        )
                        for cmd in matching_commands
                    ]
                )

        self._cache_key = text
        self._cache_completions = completions

        for c in completions:
            yield c

    def _get_command_help(self, cmd: str) -> str:
        """Get help text for a command.

        Args:
            cmd: Command name

        Returns:
            Help text
        """
        if cmd in self.help_texts:
            return self.help_texts[cmd]
        if " " in cmd:
            base, _, rest = cmd.partition(" ")
            sub_help = self.command_subcommands.get(base, {}).get(rest)
            if sub_help:
                return sub_help
        return _DEFAULT_HELP_TEXTS.get(cmd, "")


class InputHandler:
    """Enhanced input handler with completion, history, and shortcuts."""

    _suggest_cache_text: str | None
    _suggest_cache_results: list[tuple[str, str]]

    _last_completion_sync_text: str | None

    _style_cache_theme: str | None
    _style_cache: Style | None

    _prev_buffer_text: str

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

        self._suggest_cache_text = None
        self._suggest_cache_results = []
        self._last_completion_sync_text = None

        self._style_cache_theme = None
        self._style_cache = None

        self._prev_buffer_text = ""

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

        def bottom_toolbar():
            text = self.session.default_buffer.text
            suggestions = self._get_command_suggestions(text)
            if not suggestions:
                return ""

            fragments: list[tuple[str, str]] = []
            fragments.append(("class:toolbar.hint", "Commands: "))
            for i, (display, help_text) in enumerate(suggestions[:6]):
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
            # We explicitly call `Buffer.start_completion()` on slash input changes.
            # Disabling prompt_toolkit's implicit "complete while typing" avoids
            # redundant background completion tasks.
            complete_while_typing=False,
            enable_history_search=True,
            bottom_toolbar=bottom_toolbar,
        )

        # In PTK-tuned mode, reduce the default escape-sequence timeouts.
        # prompt_toolkit defaults (0.5s / 1.0s) can feel sluggish for command UIs.
        if os.environ.get("OURO_TUI") == "ptk":
            self.session.app.ttimeoutlen = 0.05
            self.session.app.timeoutlen = 0.2

        def _on_text_insert(_buffer) -> None:
            # Show/update slash completions on insertions.
            buf = self.session.default_buffer
            if not buf.text.startswith("/"):
                return

            if buf.text == self._last_completion_sync_text:
                return
            self._last_completion_sync_text = buf.text
            buf.start_completion(
                select_first=False,
                complete_event=CompleteEvent(text_inserted=True),
            )

        self.session.default_buffer.on_text_insert += _on_text_insert

        def _on_text_changed(_buffer) -> None:
            # Deletions/backspaces don't fire on_text_insert, so refresh completions here.
            buf = self.session.default_buffer
            new_text = buf.text
            prev_text = self._prev_buffer_text
            self._prev_buffer_text = new_text

            if new_text.startswith("/"):
                is_deletion = len(new_text) < len(prev_text)
                if not is_deletion:
                    return

                if new_text == self._last_completion_sync_text:
                    return
                self._last_completion_sync_text = new_text
                buf.start_completion(
                    select_first=False,
                    complete_event=CompleteEvent(text_inserted=True),
                )
                return

            self._last_completion_sync_text = None
            buf.cancel_completion()

        self.session.default_buffer.on_text_changed += _on_text_changed

    def _get_command_suggestions(self, text: str) -> list[tuple[str, str]]:
        if text == self._suggest_cache_text:
            return self._suggest_cache_results

        if not text.startswith("/"):
            self._suggest_cache_text = text
            self._suggest_cache_results = []
            return []

        cmd_text = text[1:]
        if " " in cmd_text:
            base, _, rest = cmd_text.partition(" ")
            if base in self.completer.command_subcommands and " " not in rest:
                matches = [
                    f"{base} {sub}"
                    for sub in self.completer.command_subcommands[base]
                    if sub.startswith(rest)
                ]
                results = [
                    (
                        self.completer.display_texts.get(cmd, f"/{cmd}"),
                        self.completer._get_command_help(cmd),
                    )
                    for cmd in matches
                ]
                self._suggest_cache_text = text
                self._suggest_cache_results = results
                return results

            self._suggest_cache_text = text
            self._suggest_cache_results = []
            return []

        matches = [cmd for cmd in self.completer.commands if cmd.startswith(cmd_text)]
        results = [
            (
                self.completer.display_texts.get(cmd, f"/{cmd}"),
                self.completer._get_command_help(cmd),
            )
            for cmd in matches
        ]
        self._suggest_cache_text = text
        self._suggest_cache_results = results
        return results

    def _create_key_bindings(self) -> KeyBindings:
        """Create custom key bindings.

        Returns:
            KeyBindings instance
        """
        kb = KeyBindings()

        @kb.add("/", eager=True)
        def slash_command(event):
            """Insert '/'.

            Completion triggering is handled by our on-text-changed handler.
            (Doing it here as well causes redundant completion refreshes.)
            """
            event.current_buffer.insert_text("/")

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
        theme_name = Theme.get_theme_name()
        if self._style_cache is not None and self._style_cache_theme == theme_name:
            return self._style_cache

        colors = Theme.get_colors()
        style = Style.from_dict(
            {
                "prompt": f"{colors.user_input} bold",
                "": colors.text_primary,
                "completion-menu": f"bg:{colors.bg_secondary} {colors.text_primary}",
                "completion-menu.completion": f"bg:{colors.bg_secondary} {colors.text_primary}",
                "completion-menu.completion.current": f"bg:{colors.primary} #000000",
                "completion-menu.meta.completion": f"bg:{colors.bg_secondary} {colors.text_muted}",
                "completion-menu.meta.completion.current": f"bg:{colors.primary} #000000",
                "toolbar.hint": colors.text_muted,
                "toolbar.cmd": f"{colors.primary} bold",
                "scrollbar.background": colors.bg_secondary,
                "scrollbar.button": colors.text_muted,
            }
        )
        self._style_cache_theme = theme_name
        self._style_cache = style
        return style

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
