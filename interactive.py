"""Interactive multi-turn conversation mode for the agent."""

import asyncio
import shlex
import signal

from rich.table import Table

from agent.skills import SkillsRegistry, render_skills_section
from config import Config
from llm import ModelManager
from llm.chatgpt_auth import (
    get_all_auth_provider_statuses,
    get_supported_auth_providers,
    is_auth_status_logged_in,
    login_auth_provider,
    logout_auth_provider,
)
from llm.oauth_model_sync import remove_oauth_models, sync_oauth_models
from memory import MemoryManager
from utils import get_log_file_path, terminal_ui
from utils.runtime import get_history_file
from utils.tui.command_registry import CommandRegistry, CommandSpec
from utils.tui.input_handler import InputHandler
from utils.tui.model_ui import (
    mask_secret,
    open_config_and_wait_for_save,
    parse_kv_args,
    pick_model_id,
)
from utils.tui.oauth_ui import pick_oauth_provider
from utils.tui.skills_ui import SkillsAction, pick_skills_action
from utils.tui.status_bar import StatusBar
from utils.tui.theme import Theme, set_theme


class InteractiveSession:
    """Manages an interactive conversation session with the agent."""

    def __init__(self, agent):
        """Initialize interactive session.

        Args:
            agent: The agent instance
        """
        self.agent = agent
        self.conversation_count = 0
        self.show_thinking = Config.TUI_SHOW_THINKING

        # Use the agent's model manager to avoid divergence
        self.model_manager = getattr(agent, "model_manager", None) or ModelManager()

        # Track current task for interruption support
        self.current_task = None

        # Initialize TUI components
        self.command_registry = CommandRegistry(
            commands=[
                CommandSpec("help", "Show this help message"),
                CommandSpec("reset", "Clear conversation memory and start fresh"),
                CommandSpec("stats", "Show memory and token usage statistics"),
                CommandSpec(
                    "resume",
                    "List and resume a previous session",
                    args_hint="[session_id]",
                ),
                CommandSpec("theme", "Toggle between dark and light theme"),
                CommandSpec("verbose", "Toggle verbose thinking display"),
                CommandSpec("compact", "Compress conversation memory"),
                CommandSpec("skills", "Manage skills (list/install/uninstall)"),
                CommandSpec(
                    "model",
                    "Manage models",
                    subcommands={
                        "edit": CommandSpec(
                            "edit",
                            "Edit `.ouro/models.yaml` (auto-reload on save)",
                        )
                    },
                ),
                CommandSpec("login", "Login to OAuth provider"),
                CommandSpec("logout", "Logout from OAuth provider"),
                CommandSpec("exit", "Exit interactive mode"),
            ]
        )
        self.input_handler = InputHandler(
            history_file=get_history_file(),
            command_registry=self.command_registry,
        )

        # Set up keyboard shortcut callbacks
        self.input_handler.set_callbacks(
            on_clear_screen=self._on_clear_screen,
            on_toggle_thinking=self._on_toggle_thinking,
            on_show_stats=self._on_show_stats,
        )

        # Initialize status bar
        self.status_bar = StatusBar(terminal_ui.console)
        self.status_bar.update(mode="LOOP")
        self.skills_registry = SkillsRegistry()

        # Set up signal handler for graceful interruption
        self._setup_signal_handler()

    def _setup_signal_handler(self) -> None:
        """Set up SIGINT handler for graceful task interruption."""

        def handle_sigint(sig, frame):
            """Handle SIGINT (Ctrl+C) by canceling the current task."""
            if self.current_task and not self.current_task.done():
                colors = Theme.get_colors()
                terminal_ui.console.print(
                    f"\n[bold {colors.warning}]Interrupting...[/bold {colors.warning}]"
                )
                self.current_task.cancel()
            # Don't raise - let the asyncio.CancelledError propagate

        signal.signal(signal.SIGINT, handle_sigint)

    def _on_clear_screen(self) -> None:
        """Handle Ctrl+L - clear screen."""
        terminal_ui.console.clear()

    def _on_toggle_thinking(self) -> None:
        """Handle Ctrl+T - toggle thinking display."""
        self.show_thinking = not self.show_thinking
        status = "enabled" if self.show_thinking else "disabled"
        terminal_ui.print_info(f"Thinking display {status}")

    def _on_show_stats(self) -> None:
        """Handle Ctrl+S - show quick stats."""
        self._show_stats()

    def _show_help(self) -> None:
        """Display help message with available commands."""
        colors = Theme.get_colors()
        terminal_ui.console.print(
            f"\n[bold {colors.primary}]Available Commands:[/bold {colors.primary}]"
        )
        for cmd in self.command_registry.commands:
            terminal_ui.console.print(
                f"  [{colors.primary}]{cmd.display}[/{colors.primary}] - {cmd.description}"
            )
            if cmd.subcommands:
                for sub_name, sub in cmd.subcommands.items():
                    extra = f" {sub.args_hint}" if sub.args_hint else ""
                    terminal_ui.console.print(
                        f"    [{colors.text_muted}]/{cmd.name} {sub_name}{extra} - {sub.description}[/{colors.text_muted}]"
                    )

        terminal_ui.console.print(
            f"\n[bold {colors.primary}]Keyboard Shortcuts:[/bold {colors.primary}]"
        )
        terminal_ui.console.print(
            f"  [{colors.secondary}]/[/{colors.secondary}]            - Show command suggestions"
        )
        terminal_ui.console.print(
            f"  [{colors.secondary}]Ctrl+C[/{colors.secondary}]     - Cancel current operation"
        )
        terminal_ui.console.print(
            f"  [{colors.secondary}]Ctrl+L[/{colors.secondary}]     - Clear screen"
        )
        terminal_ui.console.print(
            f"  [{colors.secondary}]Ctrl+T[/{colors.secondary}]     - Toggle thinking display"
        )
        terminal_ui.console.print(
            f"  [{colors.secondary}]Ctrl+S[/{colors.secondary}]     - Show quick stats"
        )
        terminal_ui.console.print(
            f"  [{colors.secondary}]Up/Down[/{colors.secondary}]    - Navigate command history\n"
        )

    def _show_stats(self) -> None:
        """Display current memory and token statistics."""
        terminal_ui.console.print()
        stats = self.agent.memory.get_stats()
        terminal_ui.print_memory_stats(stats)
        terminal_ui.console.print()

    async def _resume_session(self, session_id: str | None = None) -> None:
        """Resume a previous session.

        Args:
            session_id: Optional session ID or prefix. If None, shows recent sessions.
        """
        colors = Theme.get_colors()
        try:
            if session_id is None:
                # Show recent sessions for user to pick
                sessions = await MemoryManager.list_sessions(limit=10)
                if not sessions:
                    terminal_ui.console.print(
                        f"\n[{colors.warning}]No saved sessions found.[/{colors.warning}]\n"
                    )
                    return

                terminal_ui.console.print(
                    f"\n[bold {colors.primary}]Recent Sessions:[/bold {colors.primary}]\n"
                )

                table = Table(show_header=True, header_style=f"bold {colors.primary}", box=None)
                table.add_column("#", style=colors.text_muted, width=4)
                table.add_column("ID", style=colors.text_muted, width=38)
                table.add_column("Updated", width=20)
                table.add_column("Msgs", justify="right", width=6)
                table.add_column("Preview", width=50)

                for i, session in enumerate(sessions, 1):
                    sid = session["id"]
                    updated = session.get("updated_at", session.get("created_at", ""))[:19]
                    msg_count = str(session["message_count"])
                    preview = session.get("preview", "")[:50]
                    table.add_row(str(i), sid, updated, msg_count, preview)

                terminal_ui.console.print(table)
                terminal_ui.console.print(
                    f"\n[{colors.text_muted}]Usage: /resume <session_id or prefix>[/{colors.text_muted}]\n"
                )
                return

            # Resolve session ID (prefix match)
            resolved_id = await MemoryManager.find_session_by_prefix(session_id)
            if not resolved_id:
                terminal_ui.print_error(f"Session '{session_id}' not found")
                return

            # Load session via agent (agent owns memory lifecycle)
            await self.agent.load_session(resolved_id)

            msg_count = self.agent.memory.short_term.count()
            terminal_ui.print_success(
                f"Resumed session {resolved_id} ({msg_count} messages, "
                f"{self.agent.memory.current_tokens} tokens)"
            )
            terminal_ui.console.print()

            self._print_session_history()
            self._update_status_bar()

        except Exception as e:
            terminal_ui.print_error(str(e), title="Error resuming session")

    def _print_session_history(self) -> None:
        """Print conversation history from a resumed session."""
        messages = self.agent.memory.short_term.get_messages()
        if not messages:
            return

        colors = Theme.get_colors()
        terminal_ui.console.print(
            f"[bold {colors.primary}]Session History:[/bold {colors.primary}]"
        )
        terminal_ui.console.print(f"[{colors.text_muted}]{'─' * 60}[/{colors.text_muted}]")

        for msg in messages:
            if msg.role == "user":
                content = str(msg.content or "")
                if len(content) > 200:
                    content = content[:200] + "..."
                terminal_ui.console.print(
                    f"\n[bold {colors.primary}]You:[/bold {colors.primary}] {content}"
                )
            elif msg.role == "assistant" and msg.content:
                content = str(msg.content)
                if len(content) > 300:
                    content = content[:300] + "..."
                terminal_ui.console.print(
                    f"[bold {colors.secondary}]Assistant:[/bold {colors.secondary}] {content}"
                )
            elif msg.role == "assistant" and msg.tool_calls:
                tool_names = ", ".join(
                    (
                        tc.get("function", {}).get("name", "?")
                        if isinstance(tc, dict)
                        else getattr(getattr(tc, "function", None), "name", "?")
                    )
                    for tc in msg.tool_calls
                )
                terminal_ui.console.print(
                    f"[{colors.text_muted}]  (used tools: {tool_names})[/{colors.text_muted}]"
                )
            # Skip tool result messages — they are verbose

        terminal_ui.console.print(f"\n[{colors.text_muted}]{'─' * 60}[/{colors.text_muted}]\n")

    def _toggle_theme(self) -> None:
        """Toggle between dark and light theme."""
        current = Theme.get_theme_name()
        new_theme = "light" if current == "dark" else "dark"
        set_theme(new_theme)
        terminal_ui.print_success(f"Switched to {new_theme} theme")

    def _toggle_verbose(self) -> None:
        """Toggle verbose thinking display."""
        self.show_thinking = not self.show_thinking
        status = "enabled" if self.show_thinking else "disabled"
        terminal_ui.print_info(f"Verbose thinking display {status}")

    async def _compact_memory(self) -> None:
        """Compress conversation memory."""
        result = await self.agent.memory.compress()
        if result is None:
            terminal_ui.print_info("Nothing to compress.")
        else:
            terminal_ui.print_success(
                f"Compressed {result.original_message_count} messages: "
                f"{result.original_tokens} → {result.compressed_tokens} tokens "
                f"({result.savings_percentage:.0f}% saved)"
            )
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        """Update status bar with current stats."""
        stats = self.agent.memory.get_stats()
        model_info = self.agent.get_current_model_info()
        model_name = model_info["name"] if model_info else ""
        self.status_bar.update(
            input_tokens=stats.get("total_input_tokens", 0),
            output_tokens=stats.get("total_output_tokens", 0),
            context_tokens=stats.get("current_tokens", 0),
            cost=stats.get("total_cost", 0),
            model_name=model_name,
        )

    async def _handle_command(self, user_input: str) -> bool | None:
        """Handle a slash command.

        Args:
            user_input: User input starting with /

        Returns:
            True if command was handled, False if should exit, None if not handled
        """
        command_parts = user_input.split()
        command = command_parts[0].lower()

        if command in ("/exit", "/quit"):
            colors = Theme.get_colors()
            terminal_ui.console.print(
                f"\n[bold {colors.warning}]Exiting interactive mode. Goodbye![/bold {colors.warning}]"
            )
            return False

        elif command == "/help":
            self._show_help()

        elif command == "/reset":
            self.agent.memory.reset()
            self.conversation_count = 0
            self._update_status_bar()
            terminal_ui.print_success("Memory cleared. Starting fresh conversation.")
            terminal_ui.console.print()

        elif command == "/stats":
            self._show_stats()

        elif command == "/resume":
            session_id = command_parts[1] if len(command_parts) >= 2 else None
            await self._resume_session(session_id)

        elif command == "/theme":
            self._toggle_theme()

        elif command == "/verbose":
            self._toggle_verbose()

        elif command == "/compact":
            await self._compact_memory()

        elif command == "/model":
            await self._handle_model_command(user_input)

        elif command == "/login":
            await self._handle_login_command(command_parts)

        elif command == "/logout":
            await self._handle_logout_command(command_parts)

        elif command == "/skills":
            await self._handle_skills_menu()

        else:
            colors = Theme.get_colors()
            terminal_ui.console.print(
                f"[bold {colors.error}]Unknown command: {command}[/bold {colors.error}]"
            )
            terminal_ui.console.print(
                f"[{colors.text_muted}]Type /help to see available commands[/{colors.text_muted}]\n"
            )
            return True

        return True

    async def _handle_skills_menu(self) -> None:
        action = await pick_skills_action()
        if action is None:
            return

        if action == SkillsAction.LIST:
            self._show_skills_list()
            return

        if action == SkillsAction.INSTALL:
            source = await self.input_handler.prompt_async("Install path or URL: ")
            if not source:
                terminal_ui.print_warning("Install cancelled")
                return
            result = await self.skills_registry.install_skill(source)
            if result:
                terminal_ui.print_success(f"Installed skill: {result.name}")
                terminal_ui.print_info("Restart ouro to reload skills registry")
            return

        if action == SkillsAction.UNINSTALL:
            name = await self.input_handler.prompt_async("Uninstall skill name: ")
            if not name:
                terminal_ui.print_warning("Uninstall cancelled")
                return
            ok = await self.skills_registry.uninstall_skill(name)
            if ok:
                terminal_ui.print_success(f"Removed skill: {name}")
                terminal_ui.print_info("Restart ouro to reload skills registry")

    def _show_skills_list(self) -> None:
        colors = Theme.get_colors()
        skills = sorted(self.skills_registry.skills.values(), key=lambda s: s.name)
        if not skills:
            terminal_ui.print_warning("No installed skills found")
            terminal_ui.console.print()
            return

        table = Table(show_header=True, header_style=f"bold {colors.primary}", box=None)
        table.add_column("Name", style=colors.primary, width=24)
        table.add_column("Description", style=colors.text_primary)

        for skill in skills:
            table.add_row(skill.name, skill.description)

        terminal_ui.console.print(
            f"\n[bold {colors.primary}]Installed Skills:[/bold {colors.primary}]\n"
        )
        terminal_ui.console.print(table)
        terminal_ui.console.print()

    def _show_models(self) -> None:
        """Display available models and current selection."""
        colors = Theme.get_colors()
        profiles = self.model_manager.list_models()
        current = self.model_manager.get_current_model()
        default_model_id = self.model_manager.get_default_model_id()

        terminal_ui.console.print(
            f"\n[bold {colors.primary}]Available Models:[/bold {colors.primary}]\n"
        )

        if not profiles:
            terminal_ui.print_error("No models configured.")
            terminal_ui.console.print(
                f"[{colors.text_muted}]Use /model edit (recommended) or edit `.ouro/models.yaml` manually.[/{colors.text_muted}]\n"
            )
            return

        for i, profile in enumerate(profiles, start=1):
            markers: list[str] = []
            if current and profile.model_id == current.model_id:
                markers.append(f"[{colors.success}]CURRENT[/{colors.success}]")
            if default_model_id and profile.model_id == default_model_id:
                markers.append(f"[{colors.primary}]DEFAULT[/{colors.primary}]")
            marker = (
                " ".join(markers)
                if markers
                else f"[{colors.text_muted}]      [/{colors.text_muted}]"
            )

            terminal_ui.console.print(
                f"  {marker} [{colors.text_muted}]{i:>2}[/] {profile.model_id}"
            )

        terminal_ui.console.print(
            f"\n[{colors.text_muted}]Tip: run /model to pick; /model edit to change config.[/]\n"
        )

    def _switch_model(self, model_id: str) -> None:
        """Switch to a different model.

        Args:
            model_id: LiteLLM model ID to switch to
        """
        colors = Theme.get_colors()

        # Validate the profile
        profile = self.model_manager.get_model(model_id)
        if profile is None:
            terminal_ui.print_error(f"Model '{model_id}' not found")
            available = ", ".join(self.model_manager.get_model_ids())
            if available:
                terminal_ui.console.print(
                    f"[{colors.text_muted}]Available: {available}[/{colors.text_muted}]\n"
                )
            return

        is_valid, error_msg = self.model_manager.validate_model(profile)
        if not is_valid:
            terminal_ui.print_error(error_msg)
            return

        # Perform the switch
        if self.agent.switch_model(model_id):
            new_profile = self.model_manager.get_current_model()
            if new_profile:
                terminal_ui.print_success(f"Switched to model: {new_profile.model_id}")
                self._update_status_bar()
            else:
                terminal_ui.print_error("Failed to get current model after switch")
        else:
            terminal_ui.print_error(f"Failed to switch to model '{model_id}'")

    def _parse_kv_args(self, tokens: list[str]) -> tuple[dict[str, str], list[str]]:
        return parse_kv_args(tokens)

    def _mask_secret(self, value: str | None) -> str:
        return mask_secret(value)

    async def _handle_model_command(self, user_input: str) -> None:
        """Handle the /model command.

        Args:
            user_input: Full user input string
        """
        colors = Theme.get_colors()

        try:
            parts = shlex.split(user_input)
        except ValueError as e:
            terminal_ui.print_error(str(e), title="Invalid /model command")
            return

        if len(parts) == 1:
            if not self.model_manager.list_models():
                terminal_ui.print_error("No models configured yet.")
                terminal_ui.console.print(
                    f"[{colors.text_muted}]Run /model edit to configure `.ouro/models.yaml`.[/{colors.text_muted}]\n"
                )
                return
            picked = await pick_model_id(self.model_manager, title="Select Model")
            if picked:
                self._switch_model(picked)
                return
            return

        sub = parts[1]

        if sub == "edit":
            if len(parts) != 2:
                terminal_ui.print_error("Usage: /model edit")
                terminal_ui.console.print(
                    f"[{colors.text_muted}]Edit the YAML directly instead of using subcommands.[/{colors.text_muted}]\n"
                )
                return

            terminal_ui.console.print(
                f"[{colors.text_muted}]Save the file to auto-reload (Ctrl+C to cancel)...[/]\n"
            )
            ok = await open_config_and_wait_for_save(self.model_manager.config_path)
            if not ok:
                terminal_ui.print_error(
                    f"Could not open editor. Please edit `{self.model_manager.config_path}` manually."
                )
                terminal_ui.console.print(
                    f"[{colors.text_muted}]Tip: set EDITOR='code' (or similar) for /model edit.[/{colors.text_muted}]\n"
                )
                return

            self.model_manager.reload()
            terminal_ui.print_success("Reloaded `.ouro/models.yaml`")
            current_after = self.model_manager.get_current_model()
            if not current_after:
                terminal_ui.print_error(
                    "No models configured after reload. Edit `.ouro/models.yaml` and set `default`."
                )
                return

            # Reinitialize LLM adapter to pick up updated api_key/api_base/timeout/drop_params.
            self.agent.switch_model(current_after.model_id)
            terminal_ui.print_info(f"Reload applied (current: {current_after.model_id}).")
            return
        terminal_ui.print_error("Unknown /model command.")
        terminal_ui.console.print(
            f"[{colors.text_muted}]Use /model to pick, or /model edit to configure.[/{colors.text_muted}]\n"
        )

    async def _pick_auth_provider(self, mode: str) -> str | None:
        statuses = await get_all_auth_provider_statuses()
        providers: list[tuple[str, str]] = []

        for provider in get_supported_auth_providers():
            status = statuses.get(provider)
            is_logged_in = bool(status and is_auth_status_logged_in(status))
            label = "logged in" if is_logged_in else "not logged in"

            if mode == "logout" and not is_logged_in:
                continue

            providers.append((provider, label))

        if not providers:
            if mode == "logout":
                terminal_ui.print_info("No OAuth providers logged in. Use /login first.")
            else:
                terminal_ui.print_error("No OAuth providers available.")
            return None

        title = (
            "Select OAuth Provider to Login"
            if mode == "login"
            else "Select OAuth Provider to Logout"
        )
        hint = "Use ↑/↓ and Enter to select, Esc to cancel."
        return await pick_oauth_provider(providers=providers, title=title, hint=hint)

    async def _handle_login_command(self, command_parts: list[str]) -> None:
        if len(command_parts) != 1:
            terminal_ui.print_error("Usage: /login")
            return

        provider = await self._pick_auth_provider(mode="login")
        if not provider:
            return

        terminal_ui.print_info(f"Starting {provider} login flow... (Ctrl+C to cancel)")
        try:
            self.current_task = asyncio.create_task(login_auth_provider(provider))
            status = await self.current_task
        except asyncio.CancelledError:
            terminal_ui.print_warning("Login cancelled.")
            return
        except Exception as e:
            terminal_ui.print_error(str(e), title="Login Error")
            return
        finally:
            self.current_task = None

        added = sync_oauth_models(self.model_manager, provider)

        terminal_ui.print_success(f"{provider} login completed.")
        terminal_ui.console.print(f"Auth file: {status.auth_file}")
        if status.account_id:
            terminal_ui.console.print(f"Account ID: {status.account_id}")
        if added:
            terminal_ui.console.print(
                f"Added {len(added)} {provider} models to `{self.model_manager.config_path}`."
            )
        terminal_ui.print_info("Run /model to pick the active model.")

    async def _handle_logout_command(self, command_parts: list[str]) -> None:
        if len(command_parts) != 1:
            terminal_ui.print_error("Usage: /logout")
            return

        provider = await self._pick_auth_provider(mode="logout")
        if not provider:
            return

        try:
            self.current_task = asyncio.create_task(logout_auth_provider(provider))
            removed = await self.current_task
        except asyncio.CancelledError:
            terminal_ui.print_warning("Logout cancelled.")
            return
        except Exception as e:
            terminal_ui.print_error(str(e), title="Logout Error")
            return
        finally:
            self.current_task = None

        removed_models = remove_oauth_models(self.model_manager, provider)

        if removed:
            terminal_ui.print_success(f"Logged out from {provider}.")
        else:
            terminal_ui.print_info(f"No {provider} login state found.")

        if removed_models:
            terminal_ui.console.print(
                f"Removed {len(removed_models)} managed {provider} models from `{self.model_manager.config_path}`."
            )

        current_after = self.model_manager.get_current_model()
        if current_after:
            self.agent.switch_model(current_after.model_id)
            self._update_status_bar()

    async def run(self) -> None:
        """Run the interactive session loop."""
        # Print header
        terminal_ui.print_banner()

        # Display configuration
        current = self.model_manager.get_current_model()
        config_dict = {
            "Model": current.model_id if current else "NOT CONFIGURED",
            "Theme": Theme.get_theme_name(),
            "Commands": "/help for all commands",
        }
        terminal_ui.print_config(config_dict)

        colors = Theme.get_colors()

        # If session was loaded via --resume, print history
        if self.agent.memory.short_term.count() > 0:
            terminal_ui.print_info(
                f"Resumed session: {self.agent.memory.session_id} "
                f"({self.agent.memory.short_term.count()} messages)"
            )
            terminal_ui.console.print()
            self._print_session_history()

        terminal_ui.console.print(
            f"[bold {colors.success}]Interactive mode started. Type your message or use commands.[/bold {colors.success}]"
        )
        terminal_ui.console.print(
            f"[{colors.text_muted}]Tip: Type '/' for command suggestions, Ctrl+T to toggle thinking display[/{colors.text_muted}]\n"
        )

        # Show initial status bar
        if Config.TUI_STATUS_BAR:
            self.status_bar.show()

        try:
            await self.skills_registry.load()
            # Inject skills section into agent's system prompt
            skills_section = render_skills_section(list(self.skills_registry.skills.values()))
            if hasattr(self.agent, "set_skills_section"):
                self.agent.set_skills_section(skills_section)
        except Exception as e:
            terminal_ui.print_warning(f"Failed to load skills registry: {e}")

        while True:
            try:
                # Get user input
                user_input = await self.input_handler.prompt_async("> ")

                # Handle empty input
                if not user_input:
                    continue

                # Handle commands
                if user_input.startswith("/"):
                    command_result = await self._handle_command(user_input)
                    if command_result is False:
                        break
                    if command_result is True:
                        continue

                # Process user message
                self.conversation_count += 1

                # Show turn divider
                terminal_ui.print_turn_divider(self.conversation_count)

                # Echo user input in Claude Code style
                terminal_ui.print_user_message(user_input)

                # Update status bar to show processing
                if Config.TUI_STATUS_BAR:
                    self.status_bar.update(is_processing=True)

                try:
                    resolved = await self.skills_registry.resolve_user_input(user_input)
                    # Create a task for the agent run so it can be cancelled
                    self.current_task = asyncio.create_task(
                        self.agent.run(resolved.rendered, verify=False)
                    )
                    try:
                        result = await self.current_task
                    finally:
                        self.current_task = None

                    # Display agent response
                    terminal_ui.console.print(
                        f"[bold {colors.secondary}]Assistant:[/bold {colors.secondary}]"
                    )
                    terminal_ui.print_assistant_message(result)

                    # Update status bar
                    self._update_status_bar()
                    if Config.TUI_STATUS_BAR:
                        self.status_bar.update(is_processing=False)
                        self.status_bar.show()

                except asyncio.CancelledError:
                    terminal_ui.console.print(
                        f"\n[bold {colors.warning}]Task interrupted by user.[/bold {colors.warning}]\n"
                    )
                    if Config.TUI_STATUS_BAR:
                        self.status_bar.update(is_processing=False)
                    self.current_task = None

                    # Rollback incomplete exchange to prevent API errors on next turn
                    self.agent.memory.rollback_incomplete_exchange()

                    continue
                except KeyboardInterrupt:
                    terminal_ui.console.print(
                        f"\n[bold {colors.warning}]Task interrupted by user.[/bold {colors.warning}]\n"
                    )
                    if Config.TUI_STATUS_BAR:
                        self.status_bar.update(is_processing=False)
                    self.current_task = None
                    continue
                except Exception as e:
                    terminal_ui.print_error(str(e))
                    if Config.TUI_STATUS_BAR:
                        self.status_bar.update(is_processing=False)
                    continue

            except KeyboardInterrupt:
                terminal_ui.console.print(
                    f"\n\n[bold {colors.warning}]Interrupted. Type /exit to quit or continue chatting.[/bold {colors.warning}]\n"
                )
                continue
            except EOFError:
                terminal_ui.console.print(
                    f"\n[bold {colors.warning}]Exiting interactive mode. Goodbye![/bold {colors.warning}]"
                )
                break

        # Show final statistics
        terminal_ui.console.print(
            f"\n[bold {colors.primary}]Final Session Statistics:[/bold {colors.primary}]"
        )
        stats = self.agent.memory.get_stats()
        terminal_ui.print_memory_stats(stats)

        # Show log file location
        log_file = get_log_file_path()
        if log_file:
            terminal_ui.print_log_location(log_file)


class ModelSetupSession:
    """Lightweight interactive session for configuring models before the agent can run."""

    def __init__(self, model_manager: ModelManager | None = None):
        self.model_manager = model_manager or ModelManager()
        self.command_registry = CommandRegistry(
            commands=[
                CommandSpec("help", "Show this help message"),
                CommandSpec(
                    "model",
                    "Pick a model",
                    subcommands={"edit": CommandSpec("edit", "Open `.ouro/models.yaml` in editor")},
                ),
                CommandSpec("exit", "Quit"),
            ]
        )
        self.input_handler = InputHandler(
            history_file=get_history_file(),
            command_registry=self.command_registry,
        )

    def _show_help(self) -> None:
        colors = Theme.get_colors()
        terminal_ui.console.print(
            f"\n[bold {colors.primary}]Model Setup[/bold {colors.primary}] "
            f"[{colors.text_muted}](edit `.ouro/models.yaml`)[/{colors.text_muted}]\n"
        )
        terminal_ui.console.print(f"[{colors.text_muted}]Commands:[/{colors.text_muted}]\n")
        for cmd in self.command_registry.commands:
            terminal_ui.console.print(
                f"  [{colors.primary}]{cmd.display}[/{colors.primary}] - {cmd.description}"
            )
            if cmd.subcommands:
                for sub_name, sub in cmd.subcommands.items():
                    extra = f" {sub.args_hint}" if sub.args_hint else ""
                    terminal_ui.console.print(
                        f"    [{colors.text_muted}]/{cmd.name} {sub_name}{extra} - {sub.description}[/{colors.text_muted}]"
                    )

    def _show_models(self) -> None:
        colors = Theme.get_colors()
        models = self.model_manager.list_models()
        current = self.model_manager.get_current_model()
        default_model_id = self.model_manager.get_default_model_id()

        terminal_ui.console.print(
            f"\n[bold {colors.primary}]Configured Models:[/bold {colors.primary}]\n"
        )

        if not models:
            terminal_ui.print_error("No models configured yet.")
            terminal_ui.console.print(
                f"[{colors.text_muted}]Use /model edit to configure `.ouro/models.yaml`.[/{colors.text_muted}]\n"
            )
            return

        for i, model in enumerate(models, start=1):
            markers: list[str] = []
            if current and model.model_id == current.model_id:
                markers.append(f"[{colors.success}]CURRENT[/{colors.success}]")
            if default_model_id and model.model_id == default_model_id:
                markers.append(f"[{colors.primary}]DEFAULT[/{colors.primary}]")
            marker = (
                " ".join(markers)
                if markers
                else f"[{colors.text_muted}]      [/{colors.text_muted}]"
            )
            terminal_ui.console.print(f"  {marker} [{colors.text_muted}]{i:>2}[/] {model.model_id}")

        terminal_ui.console.print()
        terminal_ui.console.print(
            f"[{colors.text_muted}]Tip: run /model to pick; /model edit to change config.[/]\n"
        )

    def _parse_kv_args(self, tokens: list[str]) -> tuple[dict[str, str], list[str]]:
        return parse_kv_args(tokens)

    def _mask_secret(self, value: str | None) -> str:
        return mask_secret(value)

    async def _handle_model_command(self, user_input: str) -> bool:
        colors = Theme.get_colors()

        try:
            parts = shlex.split(user_input)
        except ValueError as e:
            terminal_ui.print_error(str(e), title="Invalid /model command")
            return False

        if len(parts) == 1:
            if not self.model_manager.list_models():
                terminal_ui.print_error("No models configured yet.")
                terminal_ui.console.print(
                    f"[{colors.text_muted}]Run /model edit to configure `.ouro/models.yaml`.[/{colors.text_muted}]\n"
                )
                return False
            picked = await pick_model_id(self.model_manager, title="Select Model")
            if picked:
                self.model_manager.set_default(picked)
                self.model_manager.switch_model(picked)
                terminal_ui.print_success(f"Selected model: {picked}")
                return self._maybe_ready_to_start()
            return False

        sub = parts[1]

        if sub == "edit":
            if len(parts) != 2:
                terminal_ui.print_error("Usage: /model edit")
                terminal_ui.console.print(
                    f"[{colors.text_muted}]Edit the YAML directly instead of using subcommands.[/{colors.text_muted}]\n"
                )
                return False

            terminal_ui.console.print(
                f"[{colors.text_muted}]Save the file to auto-reload (Ctrl+C to cancel)...[/]\n"
            )
            ok = await open_config_and_wait_for_save(self.model_manager.config_path)
            if not ok:
                terminal_ui.print_error(
                    f"Could not open editor. Please edit `{self.model_manager.config_path}` manually."
                )
                terminal_ui.console.print(
                    f"[{colors.text_muted}]Tip: set EDITOR='code' (or similar) for /model edit.[/{colors.text_muted}]\n"
                )
                return False
            self.model_manager.reload()
            terminal_ui.print_success("Reloaded `.ouro/models.yaml`")
            self._show_models()
            return self._maybe_ready_to_start()

        model_id = " ".join(parts[1:]).strip()
        if model_id and self.model_manager.get_model(model_id):
            self.model_manager.set_default(model_id)
            self.model_manager.switch_model(model_id)
            terminal_ui.print_success(f"Selected model: {model_id}")
            return self._maybe_ready_to_start()

        terminal_ui.print_error("Unknown /model command.")
        terminal_ui.console.print(
            f"[{colors.text_muted}]Use /model to pick, or /model edit to configure.[/{colors.text_muted}]\n"
        )
        return False

    def _maybe_ready_to_start(self) -> bool:
        current = self.model_manager.get_current_model()
        if not current:
            return False
        is_valid, _ = self.model_manager.validate_model(current)
        return is_valid and self.model_manager.is_configured()

    async def run(self) -> bool:
        colors = Theme.get_colors()
        terminal_ui.print_header(
            "Agentic Loop - Model Setup", subtitle="Configure `.ouro/models.yaml` to start"
        )
        terminal_ui.console.print(
            f"[{colors.text_muted}]Tip: Use /model edit (recommended) to configure, or /model to pick.[/{colors.text_muted}]\n"
        )
        self._show_help()

        while True:
            user_input = await self.input_handler.prompt_async("> ")
            if not user_input:
                continue

            # Allow typing a model_id without the /model prefix, but avoid
            # accidentally interpreting normal text as model selection.
            if not user_input.startswith("/"):
                model_ids = set(self.model_manager.get_model_ids())
                if user_input in model_ids:
                    user_input = f"/model {user_input}"
                else:
                    terminal_ui.print_error(
                        "You're in model setup mode. Pick a model or run /model edit.",
                        title="Model Setup",
                    )
                    continue

            parts = user_input.split()
            cmd = parts[0].lower()

            if cmd in ("/exit", "/quit"):
                return False

            if cmd == "/help":
                self._show_help()
                continue

            if cmd == "/model":
                ready = await self._handle_model_command(user_input)
                if ready:
                    terminal_ui.print_success("Model configuration looks good. Starting agent…")
                    return True
                continue
            terminal_ui.print_error(f"Unknown command: {cmd}. Try /help.")


async def run_interactive_mode(agent) -> None:
    """Run agent in interactive multi-turn conversation mode.

    Args:
        agent: The agent instance
    """
    session = InteractiveSession(agent)
    await session.run()


async def run_model_setup_mode(model_manager: ModelManager | None = None) -> bool:
    """Run model setup mode; returns True when ready to start agent."""
    session = ModelSetupSession(model_manager=model_manager)
    return await session.run()
