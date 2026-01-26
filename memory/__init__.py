"""Memory management system for AgenticLoop framework.

This module provides intelligent memory management with automatic compression,
token tracking, cost optimization, and optional persistence.

RFC-004 introduces graph-based memory (MemoryGraph, MemoryNode) as the new
preferred approach for composable agent architectures. The older ScopedMemoryView
is deprecated but still available for backward compatibility.
"""

from .compressor import WorkingMemoryCompressor
from .graph import MemoryGraph, MemoryNode
from .manager import MemoryManager
from .short_term import ShortTermMemory
from .store import MemoryStore
from .token_tracker import TokenTracker
from .types import CompressedMemory, CompressionStrategy

__all__ = [
    "CompressedMemory",
    "CompressionStrategy",
    "MemoryManager",
    "ShortTermMemory",
    "WorkingMemoryCompressor",
    "TokenTracker",
    "MemoryStore",
    # RFC-004: Graph-based memory
    "MemoryGraph",
    "MemoryNode",
]
