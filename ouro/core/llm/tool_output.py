"""Tool output wrapper that carries both content and metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolOutput:
    """Result from a tool execution, carrying both display content and metadata.

    Tools that need to communicate extra information to rules (e.g.
    ``is_partial_view``) can return a ``ToolOutput`` instead of a plain
    ``str``.  The executor and agent loop forward the metadata to
    ``ToolResult`` so rules can inspect it in ``after_toolcall``.
    """

    content: str
    metadata: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.content
