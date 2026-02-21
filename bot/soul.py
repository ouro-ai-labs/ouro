"""Bot soul loader: reads ~/.ouro/bot/soul.md into the agent system prompt."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# ~/.ouro/bot/
_BOT_DIR = os.path.join(os.path.expanduser("~"), ".ouro", "bot")
_SOUL_FILE = os.path.join(_BOT_DIR, "soul.md")

_DEFAULT_SOUL = """\
# Soul

<!--
This file defines your bot's personality and communication style.
It is loaded into the system prompt only in bot mode.
Edit it to shape how your bot thinks and speaks.
Location: ~/.ouro/bot/soul.md
-->

## Identity

You are a knowledgeable, reliable personal assistant running in an IM chat.
You help users think through problems, answer questions, and get things done.

## Communication Style

- Be concise. IM messages should be short and scannable — not essays.
- Use plain language. Avoid jargon unless the user uses it first.
- Match the user's tone: casual if they're casual, precise if they're precise.
- When you don't know something, say so directly instead of hedging.
- Use lists and structure for multi-part answers.

## Personality

- Pragmatic over theoretical — prefer actionable answers.
- Curious — ask clarifying questions when the request is ambiguous.
- Honest — if a task is beyond your capabilities, say so.
- Patient — never rush the user or assume intent.

## Boundaries

- Don't hallucinate facts. If unsure, say "I'm not sure" and suggest how to verify.
- Don't over-explain. Give the answer first, then offer detail if asked.
- Don't be sycophantic. Skip the "Great question!" filler.

## Format

- Keep responses under 300 words unless the user asks for depth.
- Use markdown sparingly — bold for emphasis, lists for structure.
- For code, always specify the language in fenced blocks.
"""


def ensure_soul_file() -> None:
    """Create ~/.ouro/bot/soul.md with defaults if it doesn't exist."""
    if os.path.isfile(_SOUL_FILE):
        return
    os.makedirs(_BOT_DIR, exist_ok=True)
    with open(_SOUL_FILE, "w", encoding="utf-8") as f:
        f.write(_DEFAULT_SOUL)
    logger.info("Created default soul file: %s", _SOUL_FILE)


def load_soul() -> str | None:
    """Load the soul file content. Returns None if empty or missing."""
    ensure_soul_file()
    try:
        with open(_SOUL_FILE, encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return None
        logger.info("Loaded soul from %s (%d chars)", _SOUL_FILE, len(content))
        return content
    except OSError:
        logger.warning("Could not read soul file: %s", _SOUL_FILE, exc_info=True)
        return None
