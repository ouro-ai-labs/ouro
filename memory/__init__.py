"""Memory management system for aloop framework.

This module provides intelligent memory management with automatic compression,
token tracking, cost optimization, and YAML-based persistence.

Long-term memory provides persistent knowledge storage with vector-based
semantic search via the long_term submodule.
"""

from .compressor import WorkingMemoryCompressor
from .long_term import (
    EmbeddingClient,
    Memory,
    MemoryIndexer,
    MemorySearchResult,
    Note,
    VectorStore,
)
from .manager import MemoryManager
from .short_term import ShortTermMemory
from .token_tracker import TokenTracker
from .types import CompressedMemory, CompressionStrategy

__all__ = [
    # Short-term memory
    "CompressedMemory",
    "CompressionStrategy",
    "MemoryManager",
    "ShortTermMemory",
    "WorkingMemoryCompressor",
    "TokenTracker",
    # Long-term memory
    "EmbeddingClient",
    "Memory",
    "MemoryIndexer",
    "MemorySearchResult",
    "Note",
    "VectorStore",
]
