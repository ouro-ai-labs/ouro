"""Interactive multi-turn conversation mode for the agent."""

import json
from datetime import datetime
from pathlib import Path

import aiofiles
import aiofiles.os
from rich.table import Table

from config import Config
from memory.store import MemoryStore
from utils import get_log_file_path, terminal_ui
from utils.tui.input_handler import InputHandler
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
        self.compact_mode = Config.TUI_COMPACT_MODE

        # Initialize TUI components
        self.input_handler = InputHandler(
            history_file=".agentic_loop_history",
            commands=[
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
            ],
        )

        # Set up keyboard shortcut callbacks
        self.input_handler.set_callbacks(
            on_clear_screen=self._on_clear_screen,
            on_toggle_thinking=self._on_toggle_thinking,
            on_show_stats=self._on_show_stats,
        )

        # Initialize status bar
        self.status_bar = StatusBar(terminal_ui.console)
        self.status_bar.update(mode="REACT")

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
        terminal_ui.console.print(
            f"  [{colors.primary}]/help[/{colors.primary}]             - Show this help message"
        )
        terminal_ui.console.print(
            f"  [{colors.primary}]/clear[/{colors.primary}]            - Clear conversation memory and start fresh"
        )
        terminal_ui.console.print(
            f"  [{colors.primary}]/stats[/{colors.primary}]            - Show memory and token usage statistics"
        )
        terminal_ui.console.print(
            f"  [{colors.primary}]/history[/{colors.primary}]          - List all saved conversation sessions"
        )
        terminal_ui.console.print(
            f"  [{colors.primary}]/dump-memory <id>[/{colors.primary}] - Export a session's memory to a JSON file"
        )
        terminal_ui.console.print(
            f"  [{colors.primary}]/theme[/{colors.primary}]            - Toggle between dark and light theme"
        )
        terminal_ui.console.print(
            f"  [{colors.primary}]/verbose[/{colors.primary}]          - Toggle verbose thinking display"
        )
        terminal_ui.console.print(
            f"  [{colors.primary}]/compact[/{colors.primary}]          - Toggle compact output mode"
        )
        terminal_ui.console.print(
            f"  [{colors.primary}]/exit[/{colors.primary}]             - Exit interactive mode"
        )
        terminal_ui.console.print(
            f"  [{colors.primary}]/quit[/{colors.primary}]             - Same as /exit"
        )

        terminal_ui.console.print(
            f"\n[bold {colors.primary}]Keyboard Shortcuts:[/bold {colors.primary}]"
        )
        terminal_ui.console.print(
            f"  [{colors.secondary}]Tab[/{colors.secondary}]        - Auto-complete commands"
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

    async def _show_history(self) -> None:
        """Display all saved conversation sessions."""
        try:
            store = MemoryStore(db_path="data/memory.db")
            sessions = await store.list_sessions(limit=20)

            if not sessions:
                colors = Theme.get_colors()
                terminal_ui.console.print(
                    f"\n[{colors.warning}]No saved sessions found.[/{colors.warning}]"
                )
                terminal_ui.console.print(
                    f"[{colors.text_muted}]Sessions will be saved when using persistent memory mode.[/{colors.text_muted}]\n"
                )
                return

            colors = Theme.get_colors()
            terminal_ui.console.print(
                f"\n[bold {colors.primary}]Saved Sessions (showing most recent 20):[/bold {colors.primary}]\n"
            )

            table = Table(show_header=True, header_style=f"bold {colors.primary}", box=None)
            table.add_column("ID", style=colors.text_muted, width=38)
            table.add_column("Created", width=20)
            table.add_column("Messages", justify="right", width=10)
            table.add_column("Summaries", justify="right", width=10)

            for session in sessions:
                session_id = session["id"]
                created = session["created_at"][:19]
                msg_count = str(session["message_count"])
                summary_count = str(session["summary_count"])
                table.add_row(session_id, created, msg_count, summary_count)

            terminal_ui.console.print(table)
            terminal_ui.console.print()
            terminal_ui.console.print(
                f"[{colors.text_muted}]Tip: Use /dump-memory <session_id> to export a session's memory[/{colors.text_muted}]\n"
            )

        except Exception as e:
            terminal_ui.print_error(str(e), title="Error loading sessions")

    async def _dump_memory(self, session_id: str) -> None:
        """Export a session's memory to a JSON file.

        Args:
            session_id: Session ID to export
        """
        try:
            store = MemoryStore(db_path="data/memory.db")
            session_data = await store.load_session(session_id)

            if not session_data:
                terminal_ui.print_error(f"Session {session_id} not found")
                return

            export_data = {
                "session_id": session_id,
                "exported_at": datetime.now().isoformat(),
                "stats": session_data["stats"],
                "system_messages": [msg.to_dict() for msg in session_data["system_messages"]],
                "messages": [msg.to_dict() for msg in session_data["messages"]],
                "summaries": [
                    {
                        "summary": s.summary,
                        "original_message_count": s.original_message_count,
                        "original_tokens": s.original_tokens,
                        "compressed_tokens": s.compressed_tokens,
                        "compression_ratio": s.compression_ratio,
                        "token_savings": s.token_savings,
                        "preserved_messages": [msg.to_dict() for msg in s.preserved_messages],
                        "metadata": s.metadata,
                    }
                    for s in session_data["summaries"]
                ],
            }

            output_dir = Path("dumps")
            await aiofiles.os.makedirs(str(output_dir), exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            short_id = session_id[:8]
            filename = f"memory_dump_{short_id}_{timestamp}.json"
            output_path = output_dir / filename

            async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
                payload = json.dumps(export_data, indent=2, ensure_ascii=False, default=str)
                await f.write(payload)

            terminal_ui.print_success("Memory dumped successfully!")
            colors = Theme.get_colors()
            terminal_ui.console.print(
                f"[{colors.text_muted}]Location:[/{colors.text_muted}] {output_path}"
            )

            terminal_ui.console.print(f"\n[bold {colors.primary}]Summary:[/bold {colors.primary}]")
            terminal_ui.console.print(f"  Session ID: {session_id}")
            terminal_ui.console.print(f"  Messages: {len(export_data['messages'])}")
            terminal_ui.console.print(f"  System Messages: {len(export_data['system_messages'])}")
            terminal_ui.console.print(f"  Summaries: {len(export_data['summaries'])}")
            terminal_ui.console.print()

        except Exception as e:
            terminal_ui.print_error(str(e), title="Error dumping memory")

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

    def _toggle_compact(self) -> None:
        """Toggle compact output mode."""
        self.compact_mode = not self.compact_mode
        status = "enabled" if self.compact_mode else "disabled"
        terminal_ui.print_info(f"Compact mode {status}")

    def _update_status_bar(self) -> None:
        """Update status bar with current stats."""
        stats = self.agent.memory.get_stats()
        self.status_bar.update(
            input_tokens=stats.get("total_input_tokens", 0),
            output_tokens=stats.get("total_output_tokens", 0),
            context_tokens=stats.get("current_tokens", 0),
            cost=stats.get("total_cost", 0),
        )

    async def _handle_command(self, user_input: str) -> bool:
        """Handle a slash command.

        Args:
            user_input: User input starting with /

        Returns:
            True if should continue loop, False if should exit
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

        elif command == "/clear":
            self.agent.memory.reset()
            self.conversation_count = 0
            self._update_status_bar()
            terminal_ui.print_success("Memory cleared. Starting fresh conversation.")
            terminal_ui.console.print()

        elif command == "/stats":
            self._show_stats()

        elif command == "/history":
            await self._show_history()

        elif command == "/dump-memory":
            if len(command_parts) < 2:
                terminal_ui.print_error("Please provide a session ID")
                colors = Theme.get_colors()
                terminal_ui.console.print(
                    f"[{colors.text_muted}]Usage: /dump-memory <session_id>[/{colors.text_muted}]\n"
                )
            else:
                await self._dump_memory(command_parts[1])

        elif command == "/theme":
            self._toggle_theme()

        elif command == "/verbose":
            self._toggle_verbose()

        elif command == "/compact":
            self._toggle_compact()

        else:
            colors = Theme.get_colors()
            terminal_ui.console.print(
                f"[bold {colors.error}]Unknown command: {command}[/bold {colors.error}]"
            )
            terminal_ui.console.print(
                f"[{colors.text_muted}]Type /help to see available commands[/{colors.text_muted}]\n"
            )

        return True

    async def run(self) -> None:
        """Run the interactive session loop."""
        # Print header
        terminal_ui.print_header(
            "Agentic Loop - Interactive Mode",
            subtitle="Multi-turn conversation with AI Agent",
        )

        # Display configuration
        config_dict = {
            "LLM Provider": (
                Config.LITELLM_MODEL.split("/")[0].upper()
                if "/" in Config.LITELLM_MODEL
                else "UNKNOWN"
            ),
            "Model": Config.LITELLM_MODEL,
            "Theme": Theme.get_theme_name(),
            "Commands": "/help for all commands",
        }
        terminal_ui.print_config(config_dict)

        colors = Theme.get_colors()
        terminal_ui.console.print(
            f"\n[bold {colors.success}]Interactive mode started. Type your message or use commands.[/bold {colors.success}]"
        )
        terminal_ui.console.print(
            f"[{colors.text_muted}]Tip: Press Tab for auto-complete, Ctrl+T to toggle thinking display[/{colors.text_muted}]\n"
        )

        # Show initial status bar
        if Config.TUI_STATUS_BAR:
            self.status_bar.show()

        while True:
            try:
                # Get user input
                user_input = await self.input_handler.prompt_async("> ")

                # Handle empty input
                if not user_input:
                    continue

                # Handle commands
                if user_input.startswith("/"):
                    should_continue = await self._handle_command(user_input)
                    if not should_continue:
                        break
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
                    result = await self.agent.run(user_input)

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

                except KeyboardInterrupt:
                    terminal_ui.console.print(
                        f"\n[bold {colors.warning}]Task interrupted by user.[/bold {colors.warning}]\n"
                    )
                    if Config.TUI_STATUS_BAR:
                        self.status_bar.update(is_processing=False)
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


async def run_interactive_mode(agent) -> None:
    """Run agent in interactive multi-turn conversation mode.

    Args:
        agent: The agent instance
    """
    session = InteractiveSession(agent)
    await session.run()
