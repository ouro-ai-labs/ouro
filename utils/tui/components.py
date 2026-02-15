"""Reusable UI components for the TUI."""

from typing import Any, Dict, Optional

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from utils.tui.theme import Theme


class Divider:
    """A simple horizontal divider."""

    def __init__(self, width: int = 60):
        """Initialize divider.

        Args:
            width: Width of the divider in characters
        """
        self.width = width

    def render(self, console: Console) -> None:
        """Render the divider to the console."""
        colors = Theme.get_colors()
        console.print(Text("─" * self.width, style=colors.text_muted))


class MessageDisplay:
    """Display messages in Claude Code style - clean and minimal."""

    def __init__(self, console: Console):
        """Initialize message display.

        Args:
            console: Rich console instance
        """
        self.console = console

    def user_message(self, message: str) -> None:
        """Display a user message with > prefix.

        Args:
            message: User message text
        """
        colors = Theme.get_colors()
        # User input with cyan > prefix
        prefix = Text("> ", style=f"bold {colors.user_input}")
        content = Text(message, style=colors.user_input)
        self.console.print(Text.assemble(prefix, content))
        self.console.print()

    def assistant_message(self, message: str, use_markdown: bool = True) -> None:
        """Display an assistant message.

        Args:
            message: Assistant message text
            use_markdown: Whether to render as markdown
        """
        colors = Theme.get_colors()
        if use_markdown:
            md = Markdown(message)
            self.console.print(md)
        else:
            self.console.print(Text(message, style=colors.assistant_output))
        self.console.print()

    def turn_divider(self, turn_number: Optional[int] = None) -> None:
        """Display a divider between conversation turns.

        Args:
            turn_number: Optional turn number to display
        """
        colors = Theme.get_colors()
        if turn_number is not None:
            # Divider with turn number
            left_line = "─" * 25
            right_line = "─" * 25
            turn_text = f" Turn {turn_number} "
            self.console.print(Text(f"{left_line}{turn_text}{right_line}", style=colors.text_muted))
        else:
            # Simple divider
            self.console.print(Text("─" * 60, style=colors.text_muted))
        self.console.print()


class ToolCallDisplay:
    """Display tool calls with a clean, professional look."""

    def __init__(self, console: Console):
        """Initialize tool call display.

        Args:
            console: Rich console instance
        """
        self.console = console

    def show_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Optional[str] = None,
        success: bool = True,
        duration: Optional[float] = None,
        size: Optional[str] = None,
    ) -> None:
        """Display a tool call with its arguments and optional result.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            result: Optional result summary
            success: Whether the call succeeded
            duration: Optional duration in seconds
            size: Optional result size string
        """
        colors = Theme.get_colors()

        # Build content
        lines = []

        # Arguments
        for key, value in arguments.items():
            value_str = str(value)
            if len(value_str) > 60:
                value_str = value_str[:57] + "..."
            lines.append(f"  [dim]{key}:[/dim] {value_str}")

        # Status line if result provided
        if result is not None:
            lines.append("  " + "─" * 50)
            status_icon = "✓" if success else "✗"
            status_color = colors.success if success else colors.error
            status_parts = [f"[{status_color}]{status_icon}[/{status_color}]"]
            status_parts.append("Success" if success else "Failed")
            if size:
                status_parts.append(f"({size}")
                if duration:
                    status_parts[-1] += f", {duration:.1f}s)"
                else:
                    status_parts[-1] += ")"
            elif duration:
                status_parts.append(f"({duration:.1f}s)")
            lines.append("  " + " ".join(status_parts))

        content = "\n".join(lines) if lines else ""

        # Create panel
        panel = Panel(
            content,
            title=f"[{colors.tool_accent}]Tool: {tool_name}[/{colors.tool_accent}]",
            title_align="left",
            border_style=colors.text_muted,
            box=box.ROUNDED,
            padding=(0, 1),
        )
        self.console.print(panel)


class ThinkingDisplay:
    """Display thinking/reasoning content."""

    def __init__(self, console: Console, max_preview: int = 300):
        """Initialize thinking display.

        Args:
            console: Rich console instance
            max_preview: Maximum characters to show in preview
        """
        self.console = console
        self.max_preview = max_preview

    def show(
        self,
        thinking: str,
        duration: Optional[float] = None,
        expanded: bool = False,
    ) -> None:
        """Display thinking content.

        Args:
            thinking: Thinking text
            duration: Optional duration in seconds
            expanded: Whether to show full content or preview
        """
        if not thinking:
            return

        colors = Theme.get_colors()

        # Truncate if not expanded
        if not expanded and len(thinking) > self.max_preview:
            display_text = thinking[: self.max_preview]
            display_text += f"\n[dim]... ({len(thinking) - self.max_preview} more chars)[/dim]"
        else:
            display_text = thinking

        # Build title
        title = f"[{colors.thinking_accent}]Thinking[/{colors.thinking_accent}]"

        # Build subtitle with duration
        subtitle = None
        if duration:
            subtitle = f"[dim]Duration: {duration:.1f}s[/dim]"

        panel = Panel(
            display_text,
            title=title,
            subtitle=subtitle,
            title_align="left",
            subtitle_align="right",
            border_style=colors.text_muted,
            box=box.ROUNDED,
            padding=(0, 1),
        )
        self.console.print(panel)


class MemoryStatsDisplay:
    """Display memory statistics with visual progress bars."""

    def __init__(self, console: Console):
        """Initialize memory stats display.

        Args:
            console: Rich console instance
        """
        self.console = console

    def _make_progress_bar(
        self,
        current: int,
        total: int,
        width: int = 16,
        filled_char: str = "█",
        empty_char: str = "░",
    ) -> str:
        """Create a text-based progress bar.

        Args:
            current: Current value
            total: Maximum value
            width: Width in characters
            filled_char: Character for filled portion
            empty_char: Character for empty portion

        Returns:
            Progress bar string
        """
        ratio = 0 if total == 0 else min(current / total, 1.0)
        filled = int(width * ratio)
        empty = width - filled
        return filled_char * filled + empty_char * empty

    def show(self, stats: Dict[str, Any], context_limit: int = 60000) -> None:
        """Display memory statistics.

        Args:
            stats: Statistics dictionary from memory manager
            context_limit: Maximum context window size
        """
        colors = Theme.get_colors()

        # Calculate values
        input_tokens = stats.get("total_input_tokens", 0)
        output_tokens = stats.get("total_output_tokens", 0)
        current_tokens = stats.get("current_tokens", 0)
        compression_count = stats.get("compression_count", 0)
        net_savings = stats.get("net_savings", 0)
        total_cost = stats.get("total_cost", 0)

        # Build content
        lines = []
        lines.append("  [bold]Tokens[/bold]")

        # Input tokens bar
        input_bar = self._make_progress_bar(input_tokens, context_limit)
        lines.append(f"  ├─ Input:    {input_bar}  {input_tokens:,}")

        # Output tokens bar
        output_bar = self._make_progress_bar(output_tokens, context_limit)
        lines.append(f"  ├─ Output:   {output_bar}  {output_tokens:,}")

        # Context usage
        lines.append(f"  └─ Context:  {current_tokens:,} / {context_limit // 1000}K")
        lines.append("")

        # Summary line
        savings_str = f"+{net_savings:,}" if net_savings >= 0 else f"{net_savings:,}"
        lines.append(
            f"  Cost: ${total_cost:.4f}  │  Compressions: {compression_count}  │  Saved: {savings_str}"
        )

        content = "\n".join(lines)

        panel = Panel(
            content,
            title=f"[{colors.primary}]Memory Statistics[/{colors.primary}]",
            title_align="left",
            border_style=colors.text_muted,
            box=box.ROUNDED,
            padding=(0, 1),
        )
        self.console.print(panel)
