"""Long-term memory system with vector indexing.

This module provides persistent knowledge storage with semantic search
capabilities via vector embeddings and full-text search.

Components:
- MemoryIndexer: Core indexer for parsing files and managing the search index
- EmbeddingClient: LiteLLM-based embedding generation
- VectorStore: ChromaDB storage backend

User data structure:
- ~/.aloop/memory/memories.yaml: Core memories (decisions, preferences, facts)
- ~/.aloop/memory/notes/YYYY-MM-DD.yaml: Daily notes
- ~/.aloop/memory/vector_db/: ChromaDB index storage
"""

from .embedding_client import EmbeddingClient
from .indexer import (
    SOURCE_MEMORIES,
    SOURCE_NOTES,
    VALID_CATEGORIES,
    Memory,
    MemoryIndexer,
    MemorySearchResult,
    Note,
)
from .vector_store import SearchResult, VectorStore

__all__ = [
    # Core classes
    "MemoryIndexer",
    "EmbeddingClient",
    "VectorStore",
    # Data classes
    "Memory",
    "Note",
    "MemorySearchResult",
    "SearchResult",
    # Constants
    "SOURCE_MEMORIES",
    "SOURCE_NOTES",
    "VALID_CATEGORIES",
]
