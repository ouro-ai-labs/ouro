"""Base channel protocol and message dataclasses for bot mode."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ImageData:
    """An image attachment from an IM message."""

    data: bytes  # Raw image bytes
    mime_type: str  # e.g. "image/png", "image/jpeg"


@dataclass
class FileAttachment:
    """A non-image file attachment from an IM message."""

    data: bytes
    filename: str  # e.g. "report.pdf"
    mime_type: str  # e.g. "application/pdf"


@dataclass
class IncomingMessage:
    """A message received from an IM channel."""

    channel: str  # "feishu", "slack", etc.
    conversation_id: str  # chat_id / channel_id
    user_id: str
    text: str
    message_id: str  # for deduplication
    raw: dict = field(default_factory=dict)
    images: list[ImageData] = field(default_factory=list)
    files: list[FileAttachment] = field(default_factory=list)
    platform_message_id: str = ""  # platform-native ID for reactions (Slack ts, Lark message_id)


@dataclass
class OutgoingMessage:
    """A message to send to an IM channel."""

    conversation_id: str
    text: str


# Callback type: channel implementations call this for each incoming message.
MessageCallback = Callable[[IncomingMessage], Awaitable[None]]


@runtime_checkable
class Channel(Protocol):
    """Protocol that all IM channel implementations must satisfy.

    Each channel manages its own long-lived connection to the IM platform.
    ``start()`` begins receiving messages and invokes *message_callback* for
    each one.  ``stop()`` tears down the connection cleanly.
    """

    name: str

    async def start(self, message_callback: MessageCallback) -> None:
        """Open the long connection and begin dispatching messages.

        Args:
            message_callback: Awaitable called for every incoming message.
        """
        ...

    async def stop(self) -> None:
        """Shut down the connection gracefully."""
        ...

    async def send_message(self, message: OutgoingMessage) -> None:
        """Send a message to the IM channel.

        Args:
            message: The outgoing message to send.
        """
        ...

    async def send_file(
        self,
        conversation_id: str,
        file_path: str | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        mime_type: str | None = None,
    ) -> bool:
        """Upload and send a file to the IM channel. Returns True on success."""
        ...

    async def add_reaction(self, conversation_id: str, message_id: str, emoji: str) -> str | None:
        """Add an emoji reaction to a message. Returns a reaction ID if available."""
        ...

    async def remove_reaction(
        self,
        conversation_id: str,
        message_id: str,
        emoji: str,
        reaction_id: str | None = None,
    ) -> None:
        """Remove an emoji reaction from a message."""
        ...

    async def send_typing(self, conversation_id: str) -> None:
        """Show the 'typing…' indicator in a conversation. No-op where unsupported.

        Implementations may need to be called repeatedly to keep the indicator
        visible; ``BotServer`` refreshes periodically while the agent is busy.
        """
        ...

    async def stop_typing(self, conversation_id: str) -> None:
        """Clear the 'typing…' indicator. No-op where unsupported."""
        ...
