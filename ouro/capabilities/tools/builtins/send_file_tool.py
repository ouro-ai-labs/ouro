"""Send-file tool for agents running in bot mode."""

from __future__ import annotations

import logging
import mimetypes
import os
from collections.abc import Awaitable, Callable
from typing import Any

from tools.base import BaseTool

logger = logging.getLogger(__name__)

# 50 MB hard limit
_MAX_FILE_SIZE = 50 * 1024 * 1024

# Callback signature: async (**kwargs) -> bool
SendFn = Callable[..., Awaitable[bool]]


class SendFileContext:
    """Mutable holder for the per-message send callback.

    The bot server sets the callback before each ``agent.run()`` and
    clears it afterwards so the tool cannot accidentally send to a
    stale conversation.
    """

    def __init__(self) -> None:
        self._send_fn: SendFn | None = None

    def set_send_fn(self, fn: SendFn) -> None:
        self._send_fn = fn

    def clear(self) -> None:
        self._send_fn = None

    async def send(
        self,
        file_path: str | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        mime_type: str | None = None,
    ) -> bool:
        if self._send_fn is None:
            return False
        return await self._send_fn(
            file_path=file_path,
            file_bytes=file_bytes,
            filename=filename,
            mime_type=mime_type,
        )


class SendFileTool(BaseTool):
    """Agent-facing tool to send a file to the current IM conversation."""

    def __init__(self, context: SendFileContext) -> None:
        self._ctx = context

    @property
    def name(self) -> str:
        return "send_file"

    @property
    def description(self) -> str:
        return (
            "Send a file to the user in the current IM conversation. "
            "Use this when the user asks you to create, generate, or share "
            "a file (e.g. PDF, CSV, image, document). "
            "The file must exist on disk at an absolute path."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to send.",
            },
            "filename": {
                "type": "string",
                "description": "Optional display name for the file (defaults to basename).",
                "default": "",
            },
        }

    async def execute(
        self,
        file_path: str,
        filename: str = "",
        **kwargs: Any,
    ) -> str:
        # Validate path
        if not os.path.isabs(file_path):
            return f"Error: file_path must be absolute, got: {file_path}"
        if not os.path.isfile(file_path):
            return f"Error: file not found: {file_path}"

        size = os.path.getsize(file_path)
        if size > _MAX_FILE_SIZE:
            return (
                f"Error: file too large ({size / 1024 / 1024:.1f} MB). "
                f"Maximum is {_MAX_FILE_SIZE / 1024 / 1024:.0f} MB."
            )

        display_name = filename or os.path.basename(file_path)
        mime, _ = mimetypes.guess_type(display_name)

        ok = await self._ctx.send(
            file_path=file_path,
            filename=display_name,
            mime_type=mime,
        )
        if ok:
            return f"File sent: {display_name}"
        return "Error: failed to send file (channel not available or upload failed)."
