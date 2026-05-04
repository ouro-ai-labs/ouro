"""Compaction / compression capability.

Provides working-memory compression (sliding-window, selective, deletion)
and the types used by compaction decisions.
"""

from .compressor import WorkingMemoryCompressor
from .hook import CompactionHook
from .manager import CompactionManager
from .types import CompressedMemory, CompressionStrategy

__all__ = [
    "CompressedMemory",
    "CompactionHook",
    "CompactionManager",
    "CompressionStrategy",
    "WorkingMemoryCompressor",
]
