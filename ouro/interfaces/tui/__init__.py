"""TUI (Terminal User Interface) package for ouro.

This package provides a modern, professional terminal UI with:
- Theme support (dark/light modes)
- Clean message display (Claude Code style)
- Persistent status bar
- Progress spinners and animations
- Enhanced input handling with auto-completion
"""

from utils.tui.components import (
    Divider,
    MessageDisplay,
    ThinkingDisplay,
    ToolCallDisplay,
)
from utils.tui.input_handler import InputHandler
from utils.tui.progress import ProgressContext, Spinner
from utils.tui.status_bar import StatusBar
from utils.tui.theme import Theme, get_theme, set_theme

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
