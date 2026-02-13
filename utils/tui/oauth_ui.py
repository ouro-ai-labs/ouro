"""TUI helpers for OAuth provider selection."""

from __future__ import annotations

from typing import Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from utils.tui.theme import Theme


async def pick_oauth_provider(
    providers: Sequence[tuple[str, str]],
    title: str,
    hint: str,
) -> str | None:
    """Pick an OAuth provider using a keyboard-only list.

    Args:
        providers: sequence of ``(provider_id, label)``
        title: title text
        hint: help hint text

    Returns:
        Selected provider ID, or None if cancelled.
    """
    items = list(providers)
    if not items:
        return None

    colors = Theme.get_colors()
    selected_index = 0

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event) -> None:
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(items)

    @kb.add("down")
    @kb.add("j")
    def _down(event) -> None:
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(items)

    @kb.add("enter")
    def _enter(event) -> None:
        event.app.exit(result=items[selected_index][0])

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event) -> None:
        event.app.exit(result=None)

    def _render() -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        lines.append(("class:title", f"{title}\n"))
        lines.append(("class:hint", f"{hint}\n\n"))

        for idx, (provider_id, label) in enumerate(items, start=1):
            is_selected = (idx - 1) == selected_index
            prefix = "› " if is_selected else "  "
            text = f"{prefix}{idx}. {provider_id}"
            if label:
                text += f" — {label}"
            text += "\n"

            style = "class:selected" if is_selected else "class:item"
            lines.append((style, text))

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
