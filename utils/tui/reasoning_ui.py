"""TUI helpers for selecting reasoning effort (thinking level)."""

from __future__ import annotations

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from utils.tui.theme import Theme

from llm.reasoning import REASONING_EFFORT_CHOICES

_DESC: dict[str, str] = {
    "off": "No reasoning",
    "minimal": "Very brief reasoning (~1k tokens)",
    "low": "Light reasoning (~2k tokens)",
    "medium": "Moderate reasoning (~8k tokens)",
    "high": "Deep reasoning (~16k tokens)",
    "xhigh": "Maximum reasoning (~32k tokens)",
    "default": "Use model/provider default (omit param)",
}


def _build_levels() -> list[tuple[str, str]]:
    # Derive from the canonical list so the menu stays in sync with CLI/API choices.
    allowed = set(REASONING_EFFORT_CHOICES)

    # We only show a single "off" option in UI; internally it's sent as `none`.
    allowed.discard("none")

    preferred_order = ["off", "minimal", "low", "medium", "high", "xhigh", "default"]
    levels: list[tuple[str, str]] = []

    for v in preferred_order:
        if v in allowed:
            levels.append((v, _DESC.get(v, "")))
            allowed.remove(v)

    # Any remaining values (future-proofing): keep the original declared order.
    for v in REASONING_EFFORT_CHOICES:
        if v in allowed:
            levels.append((v, _DESC.get(v, "")))
            allowed.remove(v)

    return levels


# UI labels (what we show). These map to values accepted by `agent.set_reasoning_effort`.
_LEVELS: list[tuple[str, str]] = _build_levels()


def _ui_current_value(current: str | None) -> str:
    # Internally we may store "none"; prefer showing/using "off" in the menu.
    if not current:
        return "default"
    v = current.strip().lower()
    if v == "none":
        return "off"
    return v


async def pick_reasoning_effort(
    *,
    title: str = "Thinking Level",
    subtitle: str = "Select reasoning depth for thinking-capable models",
    current: str | None = None,
) -> str | None:
    """Pick a reasoning effort using a keyboard-only list (Codex-style)."""

    colors = Theme.get_colors()
    current_value = _ui_current_value(current)

    selected_index = 0
    for i, (value, _) in enumerate(_LEVELS):
        if value == current_value:
            selected_index = i
            break

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event) -> None:
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(_LEVELS)

    @kb.add("down")
    @kb.add("j")
    def _down(event) -> None:
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(_LEVELS)

    @kb.add("enter")
    def _enter(event) -> None:
        event.app.exit(result=_LEVELS[selected_index][0])

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event) -> None:
        event.app.exit(result=None)

    def _render() -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        lines.append(("class:title", f"{title}\n"))
        lines.append(("class:hint", f"{subtitle}\n\n"))

        # Fixed-width-ish layout for readability in a monospace terminal.
        left_pad = 10
        for idx, (value, desc) in enumerate(_LEVELS):
            is_selected = idx == selected_index
            prefix = "-> " if is_selected else "   "
            left = value.ljust(left_pad)
            text = f"{prefix}{left}  {desc}\n"
            style = "class:selected" if is_selected else "class:item"
            lines.append((style, text))

        lines.append(("class:hint", "\nEnter to select. Esc to go back\n"))
        return lines

    control = FormattedTextControl(_render, focusable=True)
    window = Window(content=control, dont_extend_height=True, always_hide_cursor=True)
    layout = Layout(HSplit([window]))

    style_dict = Theme.get_prompt_toolkit_style()
    style_dict.update(
        {
            "title": f"{colors.primary} bold",
            "hint": colors.text_muted,
            "item": colors.text_primary,
            "selected": f"bg:{colors.primary} {colors.bg_primary}",
        }
    )

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=Style.from_dict(style_dict),
        full_screen=False,
        mouse_support=False,
    )
    return await app.run_async()
