"""Terminal UI utilities using Rich library for beautiful output."""

from typing import Any, Dict, Optional

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

# Global console instance
console = Console()


def print_header(title: str, subtitle: Optional[str] = None) -> None:
    """Print a formatted header panel.

    Args:
        title: Main title text
        subtitle: Optional subtitle text
    """
    content = f"[bold cyan]{title}[/bold cyan]"
    if subtitle:
        content += f"\n[dim]{subtitle}[/dim]"

    console.print(Panel(content, border_style="cyan", box=box.DOUBLE, padding=(1, 2)))


def print_config(config: Dict[str, Any]) -> None:
    """Print configuration in a formatted table.

    Args:
        config: Dictionary of configuration key-value pairs
    """
    table = Table(show_header=False, box=box.SIMPLE, border_style="blue", padding=(0, 2))
    table.add_column("Key", style="cyan bold")
    table.add_column("Value", style="green")

    for key, value in config.items():
        table.add_row(key, str(value))

    console.print(table)


def print_iteration(iteration: int, total: Optional[int] = None) -> None:
    """Print iteration header.

    Args:
        iteration: Current iteration number
        total: Optional total number of iterations
    """
    if total:
        text = Text(f"Iteration {iteration}/{total}", style="bold yellow")
    else:
        text = Text(f"Iteration {iteration}", style="bold yellow")

    console.print()
    console.rule(text, style="yellow")


def print_tool_call(tool_name: str, arguments: Dict[str, Any]) -> None:
    """Print tool call information.

    Args:
        tool_name: Name of the tool being called
        arguments: Tool arguments
    """
    # Format arguments nicely
    args_text = ""
    for key, value in arguments.items():
        value_str = str(value)
        if len(value_str) > 100:
            value_str = value_str[:97] + "..."
        args_text += f"  [cyan]{key}[/cyan]: {value_str}\n"

    console.print(f"[bold magenta]🔧 Tool:[/bold magenta] [yellow]{tool_name}[/yellow]")
    if args_text:
        console.print(args_text.rstrip())


def print_tool_result(result: str, truncated: bool = False) -> None:
    """Print tool result.

    Args:
        result: Tool result string
        truncated: Whether the result was truncated
    """
    if truncated:
        console.print("[yellow]⚠️  Result truncated[/yellow]")

    # Only show preview in verbose mode
    # console.print(f"[dim]{result_preview}...[/dim]" if len(result) > 200 else f"[dim]{result_preview}[/dim]")


def print_final_answer(answer: str) -> None:
    """Print final answer in a formatted panel with Markdown rendering.

    Args:
        answer: Final answer text (supports Markdown)
    """
    console.print()
    # Render markdown content
    md = Markdown(answer)
    console.print(
        Panel(
            md,
            title="[bold green]✓ Final Answer[/bold green]",
            border_style="green",
            box=box.DOUBLE,
            padding=(1, 2),
        )
    )


def print_memory_stats(stats: Dict[str, Any]) -> None:
    """Print memory statistics in a formatted table.

    Args:
        stats: Dictionary of memory statistics
    """
    console.print()
    console.print("[bold cyan]📊 Memory Statistics[/bold cyan]", justify="left")

    table = Table(
        show_header=True,
        header_style="bold cyan",
        box=box.ROUNDED,
        border_style="cyan",
        padding=(0, 1),
    )

    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")

    # Calculate total tokens
    total_used = stats["total_input_tokens"] + stats["total_output_tokens"]

    # Add rows
    table.add_row("Total Tokens", f"{total_used:,}")
    table.add_row("├─ Input", f"{stats['total_input_tokens']:,}")
    table.add_row("└─ Output", f"{stats['total_output_tokens']:,}")
    table.add_row("Current Context", f"{stats['current_tokens']:,}")
    table.add_row("Compressions", str(stats["compression_count"]))

    # Net savings with color
    savings = stats["net_savings"]
    savings_str = f"{savings:,}" if savings >= 0 else f"[red]{savings:,}[/red]"
    table.add_row("Net Savings", savings_str)

    table.add_row("Total Cost", f"${stats['total_cost']:.4f}")
    table.add_row(
        "Messages", f"{stats['short_term_count']} in memory, {stats['summary_count']} summaries"
    )

    console.print(table)


def print_error(message: str, title: str = "Error") -> None:
    """Print an error message.

    Args:
        message: Error message
        title: Error title (default: "Error")
    """
    console.print(
        Panel(
            f"[red]{message}[/red]",
            title=f"[bold red]❌ {title}[/bold red]",
            border_style="red",
            box=box.ROUNDED,
        )
    )


def print_warning(message: str) -> None:
    """Print a warning message.

    Args:
        message: Warning message
    """
    console.print(f"[yellow]⚠️  {message}[/yellow]")


def print_success(message: str) -> None:
    """Print a success message.

    Args:
        message: Success message
    """
    console.print(f"[green]✓ {message}[/green]")


def print_info(message: str) -> None:
    """Print an info message.

    Args:
        message: Info message
    """
    console.print(f"[blue]ℹ {message}[/blue]")


def print_log_location(log_file: str) -> None:
    """Print log file location.

    Args:
        log_file: Path to log file
    """
    console.print()
    console.print(f"[dim]📄 Detailed logs: {log_file}[/dim]")


def print_code(code: str, language: str = "python") -> None:
    """Print syntax-highlighted code.

    Args:
        code: Code string
        language: Programming language (default: python)
    """
    syntax = Syntax(code, language, theme="monokai", line_numbers=True)
    console.print(syntax)


def print_markdown(markdown_text: str) -> None:
    """Print formatted markdown.

    Args:
        markdown_text: Markdown text to render
    """
    md = Markdown(markdown_text)
    console.print(md)
