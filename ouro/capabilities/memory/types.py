"""Data types for memory management system."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

from llm.base import LLMMessage


@dataclass
class CompressedMemory:
    """Represents a compressed memory segment.

    The messages list contains ALL messages to keep after compression,
    including any summary (converted to a user message at the front).
    """

    messages: List[LLMMessage] = field(default_factory=list)  # All messages after compression
    original_message_count: int = 0
    compressed_tokens: int = 0
    original_tokens: int = 0
    compression_ratio: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def token_savings(self) -> int:
        """Calculate tokens saved by compression."""
        return self.original_tokens - self.compressed_tokens

    @property
    def savings_percentage(self) -> float:
        """Calculate percentage of tokens saved."""
        if self.original_tokens == 0:
            return 0.0
        return (self.token_savings / self.original_tokens) * 100


@dataclass
class CompressionStrategy:
    """Enum-like class for compression strategies.

    Supported strategies:
    - DELETION: Used for very few messages (<5), simply removes oldest
    - SLIDING_WINDOW: Keeps recent N messages, summarizes the rest
    - SELECTIVE: Intelligently preserves important messages, summarizes others (primary strategy)
    """

    DELETION = "deletion"  # Simply delete old messages
    SLIDING_WINDOW = "sliding_window"  # Summarize old messages, keep recent
    SELECTIVE = "selective"  # Preserve important messages, summarize others
