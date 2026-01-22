"""Interactive multi-turn conversation mode for the agent."""

import json
from datetime import datetime
from pathlib import Path

from prompt_toolkit import prompt
from prompt_toolkit.styles import Style

from config import Config
from memory.store import MemoryStore
from utils import get_log_file_path, terminal_ui


def run_interactive_mode(agent, mode: str):
    """Run agent in interactive multi-turn conversation mode.

    Args:
        agent: The agent instance
        mode: Agent mode (react or plan)
    """
    terminal_ui.print_header(
        "🤖 Agentic Loop System - Interactive Mode",
        subtitle="Multi-turn conversation with AI Agent",
    )

    # Display configuration
    config_dict = {
        "LLM Provider": (
            Config.LITELLM_MODEL.split("/")[0].upper() if "/" in Config.LITELLM_MODEL else "UNKNOWN"
        ),
        "Model": Config.LITELLM_MODEL,
        "Mode": mode.upper(),
        "Commands": "/help, /clear, /stats, /history, /dump-memory, /exit",
    }
    terminal_ui.print_config(config_dict)

    terminal_ui.console.print(
        "\n[bold green]Interactive mode started. Type your message or use commands.[/bold green]"
    )
    terminal_ui.console.print("[dim]Tip: Use /help to see available commands[/dim]\n")

    # Define prompt style for better visual feedback
    prompt_style = Style.from_dict(
        {
            "prompt": "#00ffff bold",  # Cyan bold for "You:"
        }
    )

    conversation_count = 0

    while True:
        try:
            # Get user input using prompt_toolkit for better Unicode support
            user_input = prompt([("class:prompt", "You: ")], style=prompt_style).strip()

            # Handle empty input
            if not user_input:
                continue

            # Handle special commands
            if user_input.startswith("/"):
                command_parts = user_input.split()
                command = command_parts[0].lower()

                if command == "/exit" or command == "/quit":
                    terminal_ui.console.print(
                        "\n[bold yellow]Exiting interactive mode. Goodbye![/bold yellow]"
                    )
                    break

                elif command == "/help":
                    _show_help()
                    continue

                elif command == "/clear":
                    agent.memory.reset()
                    conversation_count = 0
                    terminal_ui.console.print(
                        "\n[bold green]✓ Memory cleared. Starting fresh conversation.[/bold green]\n"
                    )
                    continue

                elif command == "/stats":
                    _show_stats(agent)
                    continue

                elif command == "/history":
                    _show_history()
                    continue

                elif command == "/dump-memory":
                    if len(command_parts) < 2:
                        terminal_ui.console.print(
                            "[bold red]Error:[/bold red] Please provide a session ID"
                        )
                        terminal_ui.console.print("[dim]Usage: /dump-memory <session_id>[/dim]\n")
                    else:
                        session_id = command_parts[1]
                        _dump_memory(session_id)
                    continue

                else:
                    terminal_ui.console.print(f"[bold red]Unknown command: {command}[/bold red]")
                    terminal_ui.console.print("[dim]Type /help to see available commands[/dim]\n")
                    continue

            # Process user message with agent
            conversation_count += 1
            terminal_ui.console.print(f"\n[dim]─── Turn {conversation_count} ───[/dim]\n")

            try:
                result = agent.run(user_input)

                # Display agent response with Markdown rendering
                terminal_ui.console.print()
                terminal_ui.console.print("[bold magenta]Assistant:[/bold magenta]")
                terminal_ui.print_markdown(result)
                terminal_ui.console.print()

            except KeyboardInterrupt:
                terminal_ui.console.print(
                    "\n[bold yellow]Task interrupted by user.[/bold yellow]\n"
                )
                continue
            except Exception as e:
                terminal_ui.console.print(f"\n[bold red]Error:[/bold red] {str(e)}\n")
                continue

        except KeyboardInterrupt:
            terminal_ui.console.print(
                "\n\n[bold yellow]Interrupted. Type /exit to quit or continue chatting.[/bold yellow]\n"
            )
            continue
        except EOFError:
            terminal_ui.console.print(
                "\n[bold yellow]Exiting interactive mode. Goodbye![/bold yellow]"
            )
            break

    # Show final statistics
    terminal_ui.console.print("\n[bold]Final Session Statistics:[/bold]")
    stats = agent.memory.get_stats()
    terminal_ui.print_memory_stats(stats)

    # Show log file location
    log_file = get_log_file_path()
    if log_file:
        terminal_ui.print_log_location(log_file)


def _show_help():
    """Display help message with available commands."""
    terminal_ui.console.print("\n[bold]Available Commands:[/bold]")
    terminal_ui.console.print("  [cyan]/help[/cyan]             - Show this help message")
    terminal_ui.console.print(
        "  [cyan]/clear[/cyan]            - Clear conversation memory and start fresh"
    )
    terminal_ui.console.print(
        "  [cyan]/stats[/cyan]            - Show memory and token usage statistics"
    )
    terminal_ui.console.print(
        "  [cyan]/history[/cyan]          - List all saved conversation sessions"
    )
    terminal_ui.console.print(
        "  [cyan]/dump-memory <id>[/cyan] - Export a session's memory to a JSON file"
    )
    terminal_ui.console.print("  [cyan]/exit[/cyan]             - Exit interactive mode")
    terminal_ui.console.print("  [cyan]/quit[/cyan]             - Same as /exit\n")


def _show_stats(agent):
    """Display current memory and token statistics."""
    terminal_ui.console.print()
    stats = agent.memory.get_stats()
    terminal_ui.print_memory_stats(stats)
    terminal_ui.console.print()


def _show_history():
    """Display all saved conversation sessions."""
    try:
        # Initialize store with default database
        store = MemoryStore(db_path="data/memory.db")
        sessions = store.list_sessions(limit=20)

        if not sessions:
            terminal_ui.console.print("\n[yellow]No saved sessions found.[/yellow]")
            terminal_ui.console.print(
                "[dim]Sessions will be saved when using persistent memory mode.[/dim]\n"
            )
            return

        terminal_ui.console.print("\n[bold]📚 Saved Sessions (showing most recent 20):[/bold]\n")

        # Create a table-like display
        from rich.table import Table

        table = Table(show_header=True, header_style="bold cyan", box=None)
        table.add_column("ID", style="dim", width=38)
        table.add_column("Created", width=20)
        table.add_column("Messages", justify="right", width=10)
        table.add_column("Summaries", justify="right", width=10)

        for session in sessions:
            session_id = session["id"]
            created = session["created_at"][:19]  # Truncate microseconds
            msg_count = str(session["message_count"])
            summary_count = str(session["summary_count"])

            table.add_row(session_id, created, msg_count, summary_count)

        terminal_ui.console.print(table)
        terminal_ui.console.print()
        terminal_ui.console.print(
            "[dim]Tip: Use /dump-memory <session_id> to export a session's memory[/dim]\n"
        )

    except Exception as e:
        terminal_ui.console.print(f"\n[bold red]Error loading sessions:[/bold red] {str(e)}\n")


def _dump_memory(session_id: str):
    """Export a session's memory to a JSON file.

    Args:
        session_id: Session ID to export
    """
    try:
        # Initialize store
        store = MemoryStore(db_path="data/memory.db")

        # Load session
        session_data = store.load_session(session_id)

        if not session_data:
            terminal_ui.console.print(
                f"\n[bold red]Error:[/bold red] Session {session_id} not found\n"
            )
            return

        # Prepare export data - use to_dict() for proper serialization including tool_calls
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

        # Create output directory
        output_dir = Path("dumps")
        output_dir.mkdir(exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_id = session_id[:8]
        filename = f"memory_dump_{short_id}_{timestamp}.json"
        output_path = output_dir / filename

        # Write to file
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)

        terminal_ui.console.print("\n[bold green]✓ Memory dumped successfully![/bold green]")
        terminal_ui.console.print(f"[dim]Location:[/dim] {output_path}")

        # Show summary
        terminal_ui.console.print("\n[bold]Summary:[/bold]")
        terminal_ui.console.print(f"  Session ID: {session_id}")
        terminal_ui.console.print(f"  Messages: {len(export_data['messages'])}")
        terminal_ui.console.print(f"  System Messages: {len(export_data['system_messages'])}")
        terminal_ui.console.print(f"  Summaries: {len(export_data['summaries'])}")
        terminal_ui.console.print()

    except Exception as e:
        terminal_ui.console.print(f"\n[bold red]Error dumping memory:[/bold red] {str(e)}\n")
