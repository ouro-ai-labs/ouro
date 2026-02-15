"""Reasoning-effort helpers (LiteLLM/OpenAI-compatible).

This module standardizes parsing/normalization for the run-scoped `reasoning_effort`
control used by LiteLLM across providers.
"""

from __future__ import annotations

from typing import Optional

# Accepted inputs (CLI / interactive). `off` is a UI-friendly alias for `none`.
REASONING_EFFORT_CHOICES: tuple[str, ...] = (
    "default",
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "off",
)

# Canonical values that may be sent to LiteLLM/OpenAI-style APIs.
_CANONICAL: set[str] = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
}


def normalize_reasoning_effort(value: Optional[str]) -> Optional[str]:
    """Normalize user input into a canonical `reasoning_effort` or None.

    Returns:
      - None for "default" / unset (meaning: omit the param entirely)
      - "none" for "off"
      - canonical string for other supported values

    Raises:
      ValueError for unknown values.
    """

    if value is None:
        return None

    v = value.strip().lower()
    if not v or v == "default":
        return None
    if v == "off":
        return "none"
    if v in _CANONICAL:
        return v

    allowed = ", ".join(REASONING_EFFORT_CHOICES)
    raise ValueError(f"Invalid reasoning_effort: {value!r}. Allowed: {allowed}")


def display_reasoning_effort(value: Optional[str]) -> str:
    """Render reasoning effort for UX (never returns None)."""

    normalized = normalize_reasoning_effort(value)
    if normalized == "none":
        # Prefer the UI-friendly label used in the TUI menu.
        return "off"
    return normalized or "default"
