"""Persistent status bar for the TUI."""

from dataclasses import dataclass
from typing import Optional

from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from utils.tui.theme import Theme


@dataclass
class StatusBarState:
    """State for the status bar."""

    mode: str = "REACT"
    input_tokens: int = 0
    output_tokens: int = 0
    context_tokens: int = 0
    cost: float = 0.0
    is_processing: bool = False
    status_message: str = ""
    model_name: str = ""


class StatusBar:
    """Persistent status bar displayed at the bottom of the terminal."""

    def __init__(self, console: Console):
        """Initialize status bar.

        Args:
            console: Rich console instance
        """
        self.console = console
        self.state = StatusBarState()
        self._live: Optional[Live] = None

    def _format_tokens(self, count: int) -> str:
        """Format token count for display.

        Args:
            count: Token count

        Returns:
            Formatted string (e.g., "12.5K" or "1.2M")
        """
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}K"
        else:
            return str(count)

    def _render(self) -> Panel:
        """Render the status bar panel.

        Returns:
            Rich Panel with status bar content
        """
        colors = Theme.get_colors()

        # Build status items
        items = []

        # Model name (if set)
        if self.state.model_name:
            items.append(
                f"[{colors.text_secondary}]Model:[/{colors.text_secondary}] [{colors.primary}]{self.state.model_name}[/{colors.primary}]"
            )

        # Mode
        items.append(
            f"[{colors.text_secondary}]Mode:[/{colors.text_secondary}] [{colors.primary}]{self.state.mode}[/{colors.primary}]"
        )

        # Total Tokens (in/out)
        total_in = self._format_tokens(self.state.input_tokens)
        total_out = self._format_tokens(self.state.output_tokens)
        items.append(
            f"[{colors.text_secondary}]Total:[/{colors.text_secondary}] {total_in}↓ {total_out}↑"
        )

        # Context Tokens
        ctx_tokens = self._format_tokens(self.state.context_tokens)
        items.append(f"[{colors.text_secondary}]Context:[/{colors.text_secondary}] {ctx_tokens}")

        # Cost
        items.append(
            f"[{colors.text_secondary}]Cost:[/{colors.text_secondary}] ${self.state.cost:.4f}"
        )

        # Processing indicator
        if self.state.is_processing:
            items.append(f"[{colors.warning}]●[/{colors.warning}]")
        else:
            items.append(f"[{colors.success}]◉[/{colors.success}]")

        # Join with separator
        content = " │ ".join(items)

        return Panel(
            Text.from_markup(content),
            box=box.DOUBLE,
            border_style=colors.text_muted,
            padding=(0, 1),
        )

    def update(
        self,
        mode: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        context_tokens: Optional[int] = None,
        cost: Optional[float] = None,
        is_processing: Optional[bool] = None,
        status_message: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        """Update status bar state.

        Args:
            mode: Agent mode (REACT, PLAN, etc.)
            input_tokens: Total input tokens used
            output_tokens: Total output tokens used
            context_tokens: Current context window tokens
            cost: Current cost
            is_processing: Whether currently processing
            status_message: Optional status message
            model_name: Current model name
        """
        if mode is not None:
            self.state.mode = mode
        if input_tokens is not None:
            self.state.input_tokens = input_tokens
        if output_tokens is not None:
            self.state.output_tokens = output_tokens
        if context_tokens is not None:
            self.state.context_tokens = context_tokens
        if cost is not None:
            self.state.cost = cost
        if is_processing is not None:
            self.state.is_processing = is_processing
        if status_message is not None:
            self.state.status_message = status_message
        if model_name is not None:
            self.state.model_name = model_name

        # Refresh live display if active
        if self._live is not None:
            self._live.update(self._render())

    def show(self) -> None:
        """Display the status bar (non-live version)."""
        self.console.print(self._render())

    def start_live(self) -> Live:
        """Start live updating status bar.

        Returns:
            Live context manager
        """
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=4,
            transient=True,
        )
        return self._live

    def stop_live(self) -> None:
        """Stop live updating."""
        if self._live is not None:
            self._live.stop()
            self._live = None
