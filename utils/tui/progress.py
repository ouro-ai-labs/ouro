"""Progress indicators and spinners for the TUI."""

import time
from contextlib import contextmanager
from typing import Generator, Optional

from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner as RichSpinner

from utils.tui.theme import Theme


class Spinner:
    """Animated spinner with context information."""

    # Spinner animation frames
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(
        self,
        console: Console,
        message: str = "Processing...",
        show_duration: bool = True,
    ):
        """Initialize spinner.

        Args:
            console: Rich console instance
            message: Message to display with spinner
            show_duration: Whether to show elapsed time
        """
        self.console = console
        self.message = message
        self.show_duration = show_duration
        self._start_time: Optional[float] = None
        self._live: Optional[Live] = None

    def _render(self) -> Panel:
        """Render the spinner panel.

        Returns:
            Rich Panel with spinner content
        """
        colors = Theme.get_colors()

        # Build spinner text with optional duration
        text = f"  {self.message}"
        if self.show_duration and self._start_time is not None:
            elapsed = time.time() - self._start_time
            text += f"\n  └─ Duration: {elapsed:.1f}s"

        # Create spinner with message
        spinner = RichSpinner("dots", text=text, style=colors.primary)

        return Panel(
            spinner,
            title=f"[{colors.thinking_accent}]Thinking[/{colors.thinking_accent}]",
            title_align="left",
            border_style=colors.text_muted,
            box=box.ROUNDED,
            padding=(0, 1),
        )

    @contextmanager
    def __call__(self, message: Optional[str] = None) -> Generator[None, None, None]:
        """Context manager for spinner display.

        Args:
            message: Optional message override

        Yields:
            None
        """
        if message:
            self.message = message

        self._start_time = time.time()
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=10,
            transient=True,
        )

        try:
            with self._live:
                yield
        finally:
            self._start_time = None
            self._live = None

    def update_message(self, message: str) -> None:
        """Update the spinner message.

        Args:
            message: New message to display
        """
        self.message = message
        if self._live is not None:
            self._live.update(self._render())


class ProgressContext:
    """Context manager for showing progress during long operations."""

    def __init__(
        self,
        console: Console,
        title: str = "Processing",
        show_steps: bool = True,
    ):
        """Initialize progress context.

        Args:
            console: Rich console instance
            title: Title for the progress display
            show_steps: Whether to show step count
        """
        self.console = console
        self.title = title
        self.show_steps = show_steps
        self._current_step = 0
        self._total_steps = 0
        self._current_message = ""
        self._start_time: Optional[float] = None
        self._live: Optional[Live] = None

    def _render(self) -> Panel:
        """Render the progress panel.

        Returns:
            Rich Panel with progress content
        """
        colors = Theme.get_colors()

        lines = []

        # Current message
        lines.append(f"  {self._current_message}")

        # Step count
        if self.show_steps and self._total_steps > 0:
            lines.append(f"  Step {self._current_step}/{self._total_steps}")

        # Duration
        if self._start_time is not None:
            elapsed = time.time() - self._start_time
            lines.append(f"  [dim]Duration: {elapsed:.1f}s[/dim]")

        content = "\n".join(lines)

        return Panel(
            content,
            title=f"[{colors.primary}]{self.title}[/{colors.primary}]",
            title_align="left",
            border_style=colors.text_muted,
            box=box.ROUNDED,
            padding=(0, 1),
        )

    def set_total_steps(self, total: int) -> None:
        """Set the total number of steps.

        Args:
            total: Total number of steps
        """
        self._total_steps = total

    def advance(self, message: str) -> None:
        """Advance to the next step.

        Args:
            message: Message for this step
        """
        self._current_step += 1
        self._current_message = message
        if self._live is not None:
            self._live.update(self._render())

    def update_message(self, message: str) -> None:
        """Update the current message without advancing.

        Args:
            message: New message
        """
        self._current_message = message
        if self._live is not None:
            self._live.update(self._render())

    @contextmanager
    def __call__(
        self, message: str = "Starting...", total_steps: int = 0
    ) -> Generator["ProgressContext", None, None]:
        """Context manager for progress display.

        Args:
            message: Initial message
            total_steps: Total number of steps (0 for indeterminate)

        Yields:
            Self for updating progress
        """
        self._current_message = message
        self._total_steps = total_steps
        self._current_step = 0
        self._start_time = time.time()

        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=4,
            transient=True,
        )

        try:
            with self._live:
                yield self
        finally:
            self._start_time = None
            self._live = None


class AsyncSpinner:
    """Async-compatible spinner for use in async contexts."""

    def __init__(
        self,
        console: Console,
        message: str = "Processing...",
    ):
        """Initialize async spinner.

        Args:
            console: Rich console instance
            message: Message to display
        """
        self.console = console
        self.message = message
        self._start_time: Optional[float] = None
        self._live: Optional[Live] = None
        self._running = False

    def _render(self) -> Panel:
        """Render the spinner panel."""
        colors = Theme.get_colors()

        spinner = RichSpinner("dots", text=f"  {self.message}", style=colors.primary)

        return Panel(
            spinner,
            title=f"[{colors.thinking_accent}]Thinking[/{colors.thinking_accent}]",
            title_align="left",
            border_style=colors.text_muted,
            box=box.ROUNDED,
            padding=(0, 1),
        )

    async def __aenter__(self) -> "AsyncSpinner":
        """Async context manager entry."""
        if self.console.quiet:
            return self
        self._start_time = time.time()
        self._running = True
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=10,
            transient=True,
        )
        self._live.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        self._running = False
        if self._live is not None:
            self._live.stop()
            self._live = None
        self._start_time = None

    def update_message(self, message: str) -> None:
        """Update the spinner message.

        Args:
            message: New message
        """
        self.message = message
        if self._live is not None and self._running:
            self._live.update(self._render())
