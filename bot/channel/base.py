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
class IncomingMessage:
    """A message received from an IM channel."""

    channel: str  # "feishu", "slack", etc.
    conversation_id: str  # chat_id / channel_id
    user_id: str
    text: str
    message_id: str  # for deduplication
    raw: dict = field(default_factory=dict)
    images: list[ImageData] = field(default_factory=list)


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
