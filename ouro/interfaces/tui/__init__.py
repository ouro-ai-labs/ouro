"""TUI (Terminal User Interface) package for ouro.

This package provides a modern, professional terminal UI with:
- Theme support (dark/light modes)
- Clean message display (Claude Code style)
- Persistent status bar
- Progress spinners and animations
- Enhanced input handling with auto-completion
"""

from ouro.interfaces.tui.components import (
    Divider,
    MessageDisplay,
    ThinkingDisplay,
    ToolCallDisplay,
)
from ouro.interfaces.tui.input_handler import InputHandler
from ouro.interfaces.tui.progress import ProgressContext, Spinner
from ouro.interfaces.tui.status_bar import StatusBar
from ouro.interfaces.tui.theme import Theme, get_theme, set_theme

__all__ = [
    # Theme
    "Theme",
    "get_theme",
    "set_theme",
    # Components
    "MessageDisplay",
    "ToolCallDisplay",
    "ThinkingDisplay",
    "Divider",
    # Status Bar
    "StatusBar",
    # Progress
    "Spinner",
    "ProgressContext",
    # Input
    "InputHandler",
]
