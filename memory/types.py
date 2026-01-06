"""Data types for memory management system."""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


@dataclass
class MemoryConfig:
    """Configuration for memory management system."""

    # Token budgets
    max_context_tokens: int = 100000  # Maximum context window
    target_working_memory_tokens: int = 50000  # Trigger compression at this level
    compression_threshold: int = 40000  # Hard limit - must compress

    # Memory windows
    short_term_message_count: int = 20  # Keep last N messages in short-term memory

    # Compression settings
    compression_ratio: float = 0.3  # Target 30% of original size
    preserve_tool_calls: bool = True  # Always preserve tool-related messages
    preserve_system_prompts: bool = True  # Always preserve system prompts

    # Cost management
    max_cost_dollars: Optional[float] = None  # Optional budget limit

    # Feature flags
    enable_compression: bool = True  # Enable/disable compression
    compression_model: Optional[str] = None  # Model to use for compression (None = same as agent)


@dataclass
class CompressedMemory:
    """Represents a compressed memory segment."""

    summary: str  # LLM-generated summary of compressed messages
    preserved_messages: List[Any] = field(default_factory=list)  # Messages to keep verbatim
    original_message_count: int = 0  # Number of original messages
    compressed_tokens: int = 0  # Token count of compressed representation
    original_tokens: int = 0  # Original token count before compression
    compression_ratio: float = 0.0  # Actual compression ratio achieved
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
    """Enum-like class for compression strategies."""

    DELETION = "deletion"  # Simply delete old messages
    SLIDING_WINDOW = "sliding_window"  # Summarize old messages, keep recent
    SELECTIVE = "selective"  # Preserve important messages, summarize others
    HIERARCHICAL = "hierarchical"  # Multi-level summarization
