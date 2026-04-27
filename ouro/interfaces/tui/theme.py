"""Theme system for TUI with dark and light mode support."""

from dataclasses import dataclass
from typing import Dict

from rich.style import Style
from rich.theme import Theme as RichTheme


@dataclass
class ThemeColors:
    """Color palette for a TUI theme."""

    # Primary colors
    primary: str  # Main accent color
    secondary: str  # Secondary accent
    success: str  # Success/positive
    warning: str  # Warning/caution
    error: str  # Error/negative

    # Background colors
    bg_primary: str  # Main background
    bg_secondary: str  # Panel/card background
    bg_highlight: str  # Highlighted areas

    # Text colors
    text_primary: str  # Primary text
    text_secondary: str  # Secondary/muted text
    text_muted: str  # Very muted text

    # Semantic colors
    user_input: str  # User input text
    assistant_output: str  # Assistant output text
    tool_accent: str  # Tool call highlights
    thinking_accent: str  # Thinking process highlights


# Dark theme - Professional, high contrast
DARK_THEME = ThemeColors(
    primary="#00D9FF",  # Bright cyan
    secondary="#A78BFA",  # Soft purple
    success="#10B981",  # Emerald green
    warning="#F59E0B",  # Amber
    error="#EF4444",  # Red
    bg_primary="#0D1117",  # Deep blue-black
    bg_secondary="#161B22",  # Slightly lighter
    bg_highlight="#21262D",  # Highlight background
    text_primary="#F0F6FC",  # Bright white
    text_secondary="#8B949E",  # Gray
    text_muted="#484F58",  # Dark gray
    user_input="#00D9FF",  # Cyan
    assistant_output="#F0F6FC",  # White
    tool_accent="#F78166",  # Orange
    thinking_accent="#A371F7",  # Purple
)

# Light theme - Clean, professional
LIGHT_THEME = ThemeColors(
    primary="#0969DA",  # Blue
    secondary="#8250DF",  # Purple
    success="#1A7F37",  # Green
    warning="#9A6700",  # Amber
    error="#CF222E",  # Red
    bg_primary="#FFFFFF",  # White
    bg_secondary="#F6F8FA",  # Light gray
    bg_highlight="#EAEEF2",  # Slightly darker
    text_primary="#1F2328",  # Near black
    text_secondary="#57606A",  # Medium gray
    text_muted="#8C959F",  # Light gray
    user_input="#0969DA",  # Blue
    assistant_output="#1F2328",  # Dark
    tool_accent="#BC4C00",  # Orange
    thinking_accent="#8250DF",  # Purple
)


class Theme:
    """TUI Theme manager."""

    _current_theme: str = "dark"
    _themes: Dict[str, ThemeColors] = {
        "dark": DARK_THEME,
        "light": LIGHT_THEME,
    }

    @classmethod
    def get_colors(cls) -> ThemeColors:
        """Get the current theme colors."""
        return cls._themes[cls._current_theme]

    @classmethod
    def set_theme(cls, name: str) -> None:
        """Set the current theme.

        Args:
            name: Theme name ('dark' or 'light')

        Raises:
            ValueError: If theme name is invalid
        """
        if name not in cls._themes:
            raise ValueError(f"Unknown theme: {name}. Available: {list(cls._themes.keys())}")
        cls._current_theme = name

    @classmethod
    def get_theme_name(cls) -> str:
        """Get the current theme name."""
        return cls._current_theme

    @classmethod
    def get_rich_theme(cls) -> RichTheme:
        """Get a Rich Theme object for the current theme."""
        colors = cls.get_colors()
        return RichTheme(
            {
                # Primary styles
                "primary": Style(color=colors.primary),
                "secondary": Style(color=colors.secondary),
                "success": Style(color=colors.success),
                "warning": Style(color=colors.warning),
                "error": Style(color=colors.error),
                # Text styles
                "text": Style(color=colors.text_primary),
                "text.secondary": Style(color=colors.text_secondary),
                "text.muted": Style(color=colors.text_muted),
                # Semantic styles
                "user": Style(color=colors.user_input, bold=True),
                "assistant": Style(color=colors.assistant_output),
                "tool": Style(color=colors.tool_accent),
                "thinking": Style(color=colors.thinking_accent),
                # UI element styles
                "panel.border": Style(color=colors.text_muted),
                "status.label": Style(color=colors.text_secondary),
                "status.value": Style(color=colors.text_primary),
                "divider": Style(color=colors.text_muted),
                # Prompt styles
                "prompt": Style(color=colors.user_input, bold=True),
                "prompt.symbol": Style(color=colors.primary, bold=True),
            }
        )

    @classmethod
    def get_prompt_toolkit_style(cls) -> Dict[str, str]:
        """Get style dict for prompt_toolkit."""
        colors = cls.get_colors()
        return {
            "prompt": colors.user_input,
            "prompt.symbol": f"{colors.primary} bold",
            "": colors.text_primary,  # Default text
            "completion-menu": f"bg:{colors.bg_secondary} {colors.text_primary}",
            "completion-menu.completion": f"bg:{colors.bg_secondary} {colors.text_primary}",
            "completion-menu.completion.current": f"bg:{colors.primary} {colors.bg_primary}",
            "scrollbar.background": colors.bg_secondary,
            "scrollbar.button": colors.text_muted,
        }


def get_theme() -> ThemeColors:
    """Get the current theme colors (convenience function)."""
    return Theme.get_colors()


def set_theme(name: str) -> None:
    """Set the current theme (convenience function)."""
    Theme.set_theme(name)
