"""Persistent status bar for the TUI."""

from dataclasses import dataclass
from typing import Optional

from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from ouro.interfaces.tui.theme import Theme


@dataclass
class StatusBarState:
    """State for the status bar."""

    input_tokens: int = 0
    output_tokens: int = 0
    context_tokens: int = 0
    cost: float = 0.0
    compression_count: int = 0
    is_processing: bool = False
    model_name: str = ""
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


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

        # Total Tokens (in/out)
        total_in = self._format_tokens(self.state.input_tokens)
        total_out = self._format_tokens(self.state.output_tokens)
        items.append(
            f"[{colors.text_secondary}]Total:[/{colors.text_secondary}] {total_in}↑ {total_out}↓"
        )

        # Cache info
        if self.state.cache_read_tokens > 0 or self.state.cache_creation_tokens > 0:
            cache_read = self._format_tokens(self.state.cache_read_tokens)
            cache_write = self._format_tokens(self.state.cache_creation_tokens)
            items.append(
                f"[{colors.text_secondary}]Cache:[/{colors.text_secondary}] "
                f"[{colors.success}]{cache_read}R[/{colors.success}] "
                f"[{colors.warning}]{cache_write}W[/{colors.warning}]"
            )

        # Context Tokens
        ctx_tokens = self._format_tokens(self.state.context_tokens)
        items.append(f"[{colors.text_secondary}]Context:[/{colors.text_secondary}] {ctx_tokens}")

        # Cost
        items.append(
            f"[{colors.text_secondary}]Cost:[/{colors.text_secondary}] ${self.state.cost:.4f}"
        )

        # Compression count
        if self.state.compression_count > 0:
            items.append(
                f"[{colors.text_secondary}]Comp:[/{colors.text_secondary}] [{colors.warning}]×{self.state.compression_count}[/{colors.warning}]"
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
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        context_tokens: Optional[int] = None,
        cost: Optional[float] = None,
        compression_count: Optional[int] = None,
        is_processing: Optional[bool] = None,
        model_name: Optional[str] = None,
        cache_read_tokens: Optional[int] = None,
        cache_creation_tokens: Optional[int] = None,
    ) -> None:
        """Update status bar state.

        Args:
            input_tokens: Total input tokens used
            output_tokens: Total output tokens used
            context_tokens: Current context window tokens
            cost: Current cost
            compression_count: Number of memory compressions performed
            is_processing: Whether currently processing
            model_name: Current model name
            cache_read_tokens: Total cache read tokens
            cache_creation_tokens: Total cache creation (write) tokens
        """
        if input_tokens is not None:
            self.state.input_tokens = input_tokens
        if output_tokens is not None:
            self.state.output_tokens = output_tokens
        if context_tokens is not None:
            self.state.context_tokens = context_tokens
        if cost is not None:
            self.state.cost = cost
        if compression_count is not None:
            self.state.compression_count = compression_count
        if is_processing is not None:
            self.state.is_processing = is_processing
        if model_name is not None:
            self.state.model_name = model_name
        if cache_read_tokens is not None:
            self.state.cache_read_tokens = cache_read_tokens
        if cache_creation_tokens is not None:
            self.state.cache_creation_tokens = cache_creation_tokens

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
