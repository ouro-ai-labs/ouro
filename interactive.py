"""Interactive multi-turn conversation mode for the agent."""
from config import Config
from utils import get_log_file_path, terminal_ui


def run_interactive_mode(agent, mode: str):
    """Run agent in interactive multi-turn conversation mode.

    Args:
        agent: The agent instance
        mode: Agent mode (react or plan)
    """
    terminal_ui.print_header(
        "🤖 Agentic Loop System - Interactive Mode",
        subtitle="Multi-turn conversation with AI Agent"
    )

    # Display configuration
    config_dict = {
        "LLM Provider": Config.LLM_PROVIDER.upper(),
        "Model": Config.get_default_model(),
        "Mode": mode.upper(),
        "Commands": "/help, /clear, /stats, /exit"
    }
    terminal_ui.print_config(config_dict)

    terminal_ui.console.print("\n[bold green]Interactive mode started. Type your message or use commands.[/bold green]")
    terminal_ui.console.print("[dim]Tip: Use /help to see available commands[/dim]\n")

    conversation_count = 0

    while True:
        try:
            # Get user input
            terminal_ui.console.print("[bold cyan]You:[/bold cyan] ", end="")
            user_input = input().strip()

            # Handle empty input
            if not user_input:
                continue

            # Handle special commands
            if user_input.startswith("/"):
                command = user_input.lower()

                if command == "/exit" or command == "/quit":
                    terminal_ui.console.print("\n[bold yellow]Exiting interactive mode. Goodbye![/bold yellow]")
                    break

                elif command == "/help":
                    _show_help()
                    continue

                elif command == "/clear":
                    agent.memory.reset()
                    conversation_count = 0
                    terminal_ui.console.print("\n[bold green]✓ Memory cleared. Starting fresh conversation.[/bold green]\n")
                    continue

                elif command == "/stats":
                    _show_stats(agent)
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
                terminal_ui.console.print("\n[bold yellow]Task interrupted by user.[/bold yellow]\n")
                continue
            except Exception as e:
                terminal_ui.console.print(f"\n[bold red]Error:[/bold red] {str(e)}\n")
                continue

        except KeyboardInterrupt:
            terminal_ui.console.print("\n\n[bold yellow]Interrupted. Type /exit to quit or continue chatting.[/bold yellow]\n")
            continue
        except EOFError:
            terminal_ui.console.print("\n[bold yellow]Exiting interactive mode. Goodbye![/bold yellow]")
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
    terminal_ui.console.print("  [cyan]/help[/cyan]   - Show this help message")
    terminal_ui.console.print("  [cyan]/clear[/cyan]  - Clear conversation memory and start fresh")
    terminal_ui.console.print("  [cyan]/stats[/cyan]  - Show memory and token usage statistics")
    terminal_ui.console.print("  [cyan]/exit[/cyan]   - Exit interactive mode")
    terminal_ui.console.print("  [cyan]/quit[/cyan]   - Same as /exit\n")


def _show_stats(agent):
    """Display current memory and token statistics."""
    terminal_ui.console.print()
    stats = agent.memory.get_stats()
    terminal_ui.print_memory_stats(stats)
    terminal_ui.console.print()
