"""Terminal UI utilities using Rich library for beautiful output.

This module provides a unified interface for terminal output, integrating
with the TUI theme system for consistent styling.
"""

from typing import Any, Dict, Optional

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from config import Config
from utils.tui.theme import Theme, set_theme

# Initialize theme from config
set_theme(Config.TUI_THEME)

# Global console instance with theme support
console = Console(theme=Theme.get_rich_theme())


def _get_colors():
    """Get current theme colors."""
    return Theme.get_colors()


ALOOP_LOGO = r"""
 █████╗ ██╗      ██████╗  ██████╗ ██████╗
██╔══██╗██║     ██╔═══██╗██╔═══██╗██╔══██╗
███████║██║     ██║   ██║██║   ██║██████╔╝
██╔══██║██║     ██║   ██║██║   ██║██╔═══╝
██║  ██║███████╗╚██████╔╝╚██████╔╝██║
╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝ ╚═╝"""


TAGLINES = [
    "Think. Act. Observe. Repeat.",
    "Your terminal, now with agency.",
    "Reasoning in loops, so you don't have to.",
    "One loop to rule them all.",
    "Where thoughts become tool calls.",
    "The agent that thinks before it acts. Usually.",
    "Ctrl+C is your safe word.",
    "Turning vibes into function calls since 2025.",
    "I think, therefore I tool_call.",
    "sudo make me a sandwich. Actually, I can do that now.",
]


def print_banner(subtitle: Optional[str] = None) -> None:
    """Print the ASCII art banner with a random tagline."""
    import random

    colors = _get_colors()
    content = f"[bold {colors.primary}]{ALOOP_LOGO.lstrip(chr(10))}[/bold {colors.primary}]"
    tagline = subtitle or random.choice(TAGLINES)
    content += f"\n\n[italic {colors.secondary}]{tagline}[/italic {colors.secondary}]"

    console.print(Panel(content, border_style=colors.primary, box=box.DOUBLE, padding=(1, 2)))


def print_header(title: str, subtitle: Optional[str] = None) -> None:
    """Print a formatted header panel.

    Args:
        title: Main title text
        subtitle: Optional subtitle text
    """
    colors = _get_colors()
    content = f"[bold {colors.primary}]{title}[/bold {colors.primary}]"
    if subtitle:
        content += f"\n[{colors.text_secondary}]{subtitle}[/{colors.text_secondary}]"

    console.print(Panel(content, border_style=colors.primary, box=box.DOUBLE, padding=(1, 2)))


def print_config(config: Dict[str, Any]) -> None:
    """Print configuration in a formatted table.

    Args:
        config: Dictionary of configuration key-value pairs
    """
    colors = _get_colors()
    table = Table(show_header=False, box=box.SIMPLE, border_style=colors.text_muted, padding=(0, 2))
    table.add_column("Key", style=f"{colors.primary} bold")
    table.add_column("Value", style=colors.success)

    for key, value in config.items():
        table.add_row(key, str(value))

    console.print(table)


def print_thinking(thinking: str, max_length: Optional[int] = None) -> None:
    """Print AI thinking/reasoning content.

    Args:
        thinking: Thinking content string
        max_length: Maximum length to display (uses config default if None)
    """
    if not thinking:
        return

    if not Config.TUI_SHOW_THINKING:
        return

    colors = _get_colors()
    max_len = max_length if max_length is not None else Config.TUI_THINKING_MAX_PREVIEW

    # Truncate if too long
    if len(thinking) > max_len:
        display_text = (
            thinking[:max_len]
            + f"... [{colors.text_muted}]({len(thinking) - max_len} more chars)[/{colors.text_muted}]"
        )
    else:
        display_text = thinking

    console.print(
        Panel(
            display_text,
            title=f"[bold {colors.thinking_accent}]Thinking[/bold {colors.thinking_accent}]",
            border_style=colors.text_muted,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def print_tool_call(tool_name: str, arguments: Dict[str, Any]) -> None:
    """Print tool call information.

    Args:
        tool_name: Name of the tool being called
        arguments: Tool arguments
    """
    colors = _get_colors()

    # Format arguments nicely
    args_lines = []
    for key, value in arguments.items():
        value_str = str(value)
        if len(value_str) > 100:
            value_str = value_str[:97] + "..."
        args_lines.append(
            f"  [{colors.text_secondary}]{key}:[/{colors.text_secondary}] {value_str}"
        )

    content = "\n".join(args_lines) if args_lines else ""

    console.print(
        Panel(
            content,
            title=f"[{colors.tool_accent}]Tool: {tool_name}[/{colors.tool_accent}]",
            title_align="left",
            border_style=colors.text_muted,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def print_tool_result(
    result: str,
    truncated: bool = False,
    success: bool = True,
    duration: Optional[float] = None,
) -> None:
    """Print tool result.

    Args:
        result: Tool result string
        truncated: Whether the result was truncated
        success: Whether the tool call succeeded
        duration: Optional duration in seconds
    """
    colors = _get_colors()

    if truncated:
        console.print(f"[{colors.warning}]Result truncated[/{colors.warning}]")

    # Show status line
    status_icon = "✓" if success else "✗"
    status_color = colors.success if success else colors.error
    status_parts = [f"[{status_color}]{status_icon}[/{status_color}]"]

    if duration:
        status_parts.append(f"({duration:.1f}s)")

    if status_parts:
        console.print(" ".join(status_parts))


def print_final_answer(answer: str) -> None:
    """Print final answer in a formatted panel with Markdown rendering.

    Args:
        answer: Final answer text (supports Markdown)
    """
    colors = _get_colors()
    console.print()
    # Render markdown content
    md = Markdown(answer)
    console.print(
        Panel(
            md,
            title=f"[bold {colors.success}]Final Answer[/bold {colors.success}]",
            border_style=colors.success,
            box=box.DOUBLE,
            padding=(1, 2),
        )
    )


def print_unfinished_answer(answer: str) -> None:
    """Print an intermediate answer that did not pass verification.

    Args:
        answer: Answer text (supports Markdown)
    """
    colors = _get_colors()
    console.print()
    md = Markdown(answer)
    console.print(
        Panel(
            md,
            title=f"[bold {colors.warning}]Unfinished Answer[/bold {colors.warning}]",
            border_style=colors.warning,
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def print_memory_stats(stats: Dict[str, Any]) -> None:
    """Print memory statistics in a formatted table.

    Args:
        stats: Dictionary of memory statistics
    """
    colors = _get_colors()
    console.print()
    console.print(
        f"[bold {colors.primary}]Memory Statistics[/bold {colors.primary}]", justify="left"
    )

    table = Table(
        show_header=True,
        header_style=f"bold {colors.primary}",
        box=box.ROUNDED,
        border_style=colors.text_muted,
        padding=(0, 1),
    )

    table.add_column("Metric", style=colors.primary)
    table.add_column("Value", justify="right", style=colors.success)

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
    savings_str = (
        f"{savings:,}" if savings >= 0 else f"[{colors.error}]{savings:,}[/{colors.error}]"
    )
    table.add_row("Net Savings", savings_str)

    table.add_row("Total Cost", f"${stats['total_cost']:.4f}")
    table.add_row("Messages", f"{stats['short_term_count']} in memory")

    console.print(table)


def print_error(message: str, title: str = "Error") -> None:
    """Print an error message.

    Args:
        message: Error message
        title: Error title (default: "Error")
    """
    colors = _get_colors()
    console.print(
        Panel(
            f"[{colors.error}]{message}[/{colors.error}]",
            title=f"[bold {colors.error}]{title}[/bold {colors.error}]",
            border_style=colors.error,
            box=box.ROUNDED,
        )
    )


def print_warning(message: str) -> None:
    """Print a warning message.

    Args:
        message: Warning message
    """
    colors = _get_colors()
    console.print(f"[{colors.warning}]{message}[/{colors.warning}]")


def print_success(message: str) -> None:
    """Print a success message.

    Args:
        message: Success message
    """
    colors = _get_colors()
    console.print(f"[{colors.success}]✓ {message}[/{colors.success}]")


def print_info(message: str) -> None:
    """Print an info message.

    Args:
        message: Info message
    """
    colors = _get_colors()
    console.print(f"[{colors.primary}]ℹ {message}[/{colors.primary}]")


def print_log_location(log_file: str) -> None:
    """Print log file location.

    Args:
        log_file: Path to log file
    """
    colors = _get_colors()
    console.print()
    console.print(f"[{colors.text_muted}]Detailed logs: {log_file}[/{colors.text_muted}]")


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


def print_divider(width: int = 60) -> None:
    """Print a horizontal divider.

    Args:
        width: Width of the divider in characters
    """
    colors = _get_colors()
    console.print(Text("─" * width, style=colors.text_muted))


def print_user_message(message: str) -> None:
    """Print a user message in Claude Code style.

    Args:
        message: User message text
    """
    colors = _get_colors()
    prefix = Text("> ", style=f"bold {colors.user_input}")
    content = Text(message, style=colors.user_input)
    console.print(Text.assemble(prefix, content))
    if not Config.TUI_COMPACT_MODE:
        console.print()


def print_assistant_message(message: str, use_markdown: bool = True) -> None:
    """Print an assistant message.

    Args:
        message: Assistant message text
        use_markdown: Whether to render as markdown
    """
    colors = _get_colors()
    if use_markdown:
        md = Markdown(message)
        console.print(md)
    else:
        console.print(Text(message, style=colors.assistant_output))
    if not Config.TUI_COMPACT_MODE:
        console.print()


def print_turn_divider(turn_number: Optional[int] = None) -> None:
    """Print a divider between conversation turns.

    Args:
        turn_number: Optional turn number to display
    """
    colors = _get_colors()
    if turn_number is not None:
        left_line = "─" * 25
        right_line = "─" * 25
        turn_text = f" Turn {turn_number} "
        console.print(Text(f"{left_line}{turn_text}{right_line}", style=colors.text_muted))
    else:
        console.print(Text("─" * 60, style=colors.text_muted))
    if not Config.TUI_COMPACT_MODE:
        console.print()
