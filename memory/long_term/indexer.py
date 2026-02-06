"""Memory indexer for long-term memory management.

This module provides the core indexer that parses memory files,
detects changes, and maintains a vector/full-text index for search.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import aiofiles
import aiofiles.os
import yaml

from utils import get_logger

from .embedding_client import EmbeddingClient
from .vector_store import VectorStore

if TYPE_CHECKING:
    from llm.model_manager import ModelManager

logger = get_logger(__name__)

# Memory categories
VALID_CATEGORIES = {"decision", "preference", "fact"}

# Source types
SOURCE_MEMORIES = "memories"
SOURCE_NOTES = "notes"


@dataclass
class Memory:
    """A single memory entry."""

    id: str
    content: str
    category: str
    created_at: str
    source: str = SOURCE_MEMORIES
    keywords: list[str] = field(default_factory=list)


@dataclass
class Note:
    """A note entry from a daily note file."""

    id: str
    content: str
    date: str
    time: str
    tags: list[str] = field(default_factory=list)


@dataclass
class MemorySearchResult:
    """A memory search result with relevance score."""

    content: str
    source: str  # "memories" or "notes"
    category: str | None  # For memories
    date: str | None  # For notes
    score: float  # 0-1, higher is better (converted from distance)
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryIndexer:
    """Memory indexer for long-term knowledge storage.

    Parses memory files (memories.yaml and notes/*.yaml), detects changes,
    and maintains a vector/full-text index for semantic search.

    File structure:
    - ~/.aloop/memory/memories.yaml: Core memories (decisions, preferences, facts)
    - ~/.aloop/memory/notes/YYYY-MM-DD.yaml: Daily notes

    The indexer uses file hashing to detect changes and only re-indexes
    modified files. Embeddings are generated via LiteLLM and stored in ChromaDB.
    """

    VERSION = 2  # Schema version for memories.yaml

    def __init__(
        self,
        memory_dir: str | None = None,
        model_manager: ModelManager | None = None,
        embedding_client: EmbeddingClient | None = None,
    ):
        """Initialize the memory indexer.

        Args:
            memory_dir: Directory for memory storage. Defaults to ~/.aloop/memory/
            model_manager: Optional ModelManager for embedding configuration.
            embedding_client: Optional pre-configured embedding client.
        """
        if memory_dir is None:
            memory_dir = os.path.join(os.path.expanduser("~"), ".aloop", "memory")

        self._memory_dir = memory_dir
        self._model_manager = model_manager

        # Initialize embedding client
        if embedding_client:
            self._embedding_client = embedding_client
        else:
            self._embedding_client = EmbeddingClient(model_manager=model_manager)

        # Initialize vector store
        self._vector_store = VectorStore(
            storage_dir=memory_dir,
            embedding_dim=self._embedding_client.embedding_dim,
        )

        # File hash cache for change detection
        self._file_hashes: dict[str, str] = {}

        # In-memory cache of memories
        self._memories: list[Memory] = []
        self._loaded = False

    @property
    def memory_dir(self) -> str:
        """Get the memory directory path."""
        return self._memory_dir

    @property
    def memories_file(self) -> str:
        """Get the memories.yaml file path."""
        return os.path.join(self._memory_dir, "memories.yaml")

    @property
    def notes_dir(self) -> str:
        """Get the notes directory path."""
        return os.path.join(self._memory_dir, "notes")

    async def _ensure_dirs(self) -> None:
        """Ensure memory directories exist."""
        for path in [self._memory_dir, self.notes_dir]:
            if not await aiofiles.os.path.exists(path):
                os.makedirs(path, exist_ok=True)

    def _compute_file_hash(self, content: str) -> str:
        """Compute hash of file content for change detection."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    async def _load_memories_file(self) -> list[Memory]:
        """Load memories from memories.yaml."""
        if not await aiofiles.os.path.exists(self.memories_file):
            return []

        async with aiofiles.open(self.memories_file, encoding="utf-8") as f:
            content = await f.read()

        if not content.strip():
            return []

        data = yaml.safe_load(content)
        if not data or "memories" not in data:
            return []

        return [
            Memory(
                id=m.get("id", str(uuid.uuid4())[:8]),
                content=m.get("content", ""),
                category=m.get("category", "fact"),
                created_at=m.get("created_at", datetime.now().isoformat()),
                source=SOURCE_MEMORIES,
                keywords=m.get("keywords", []),
            )
            for m in data.get("memories", [])
        ]

    async def _load_notes_file(self, filepath: str) -> list[Note]:
        """Load notes from a single note file."""
        if not await aiofiles.os.path.exists(filepath):
            return []

        async with aiofiles.open(filepath, encoding="utf-8") as f:
            content = await f.read()

        if not content.strip():
            return []

        data = yaml.safe_load(content)
        if not data:
            return []

        date = data.get("date", os.path.basename(filepath).replace(".yaml", ""))
        return [
            Note(
                id=entry.get("id", str(uuid.uuid4())[:8]),
                content=entry.get("content", ""),
                date=date,
                time=entry.get("time", "00:00:00"),
                tags=entry.get("tags", []),
            )
            for entry in data.get("entries", [])
        ]

    async def _get_all_note_files(self) -> list[str]:
        """Get all note files in the notes directory."""
        if not await aiofiles.os.path.exists(self.notes_dir):
            return []

        files = [
            os.path.join(self.notes_dir, filename)
            for filename in os.listdir(self.notes_dir)
            if filename.endswith(".yaml")
        ]
        return sorted(files)

    async def sync(self) -> dict[str, int]:
        """Synchronize memory index with file changes.

        Detects changed files and updates the vector index accordingly.

        Returns:
            Dict with counts of indexed, updated, and deleted documents.
        """
        await self._ensure_dirs()

        stats = {"indexed": 0, "updated": 0, "deleted": 0}

        # Check if embedding is configured
        if not self._embedding_client.is_configured():
            logger.warning("Embedding not configured, skipping index sync")
            return stats

        # Track current doc IDs to detect deletions
        current_doc_ids: set[str] = set()

        # Process memories.yaml
        if await aiofiles.os.path.exists(self.memories_file):
            async with aiofiles.open(self.memories_file, encoding="utf-8") as f:
                content = await f.read()

            file_hash = self._compute_file_hash(content)
            old_hash = self._file_hashes.get(self.memories_file)

            if file_hash != old_hash:
                # File changed, re-index
                memories = await self._load_memories_file()
                await self._index_memories(memories)
                self._file_hashes[self.memories_file] = file_hash
                stats["updated"] += len(memories)

                for m in memories:
                    current_doc_ids.add(f"memory:{m.id}")
            else:
                # No change, just collect IDs
                memories = await self._load_memories_file()
                for m in memories:
                    current_doc_ids.add(f"memory:{m.id}")

        # Process note files
        note_files = await self._get_all_note_files()
        for filepath in note_files:
            async with aiofiles.open(filepath, encoding="utf-8") as f:
                content = await f.read()

            file_hash = self._compute_file_hash(content)
            old_hash = self._file_hashes.get(filepath)

            if file_hash != old_hash:
                # File changed, re-index
                notes = await self._load_notes_file(filepath)
                await self._index_notes(notes)
                self._file_hashes[filepath] = file_hash
                stats["updated"] += len(notes)

                for n in notes:
                    current_doc_ids.add(f"note:{n.id}")
            else:
                # No change, just collect IDs
                notes = await self._load_notes_file(filepath)
                for n in notes:
                    current_doc_ids.add(f"note:{n.id}")

        # Handle deletions (existing IDs not in current files)
        existing_count = await self._vector_store.count()
        if existing_count > len(current_doc_ids):
            # Some documents were deleted, but ChromaDB doesn't support
            # easy iteration, so we'll skip deletion detection for now
            pass

        return stats

    async def _index_memories(self, memories: list[Memory]) -> None:
        """Index a list of memories into the vector store."""
        if not memories:
            return

        # Delete existing memory documents first
        await self._vector_store.delete_by_metadata({"source": SOURCE_MEMORIES})

        # Prepare batch data
        doc_ids = [f"memory:{m.id}" for m in memories]
        contents = [m.content for m in memories]
        metadatas = [
            {
                "source": SOURCE_MEMORIES,
                "category": m.category,
                "created_at": m.created_at,
                "keywords": ",".join(m.keywords),
            }
            for m in memories
        ]

        # Generate embeddings
        try:
            embeddings = await self._embedding_client.embed_batch(contents)
        except Exception as e:
            logger.error(f"Failed to generate embeddings: {e}")
            return

        # Upsert to vector store
        await self._vector_store.upsert_batch(doc_ids, contents, embeddings, metadatas)

    async def _index_notes(self, notes: list[Note]) -> None:
        """Index a list of notes into the vector store."""
        if not notes:
            return

        # Group notes by date for batch deletion
        dates = {n.date for n in notes}
        for date in dates:
            await self._vector_store.delete_by_metadata({"source": SOURCE_NOTES, "date": date})

        # Prepare batch data
        doc_ids = [f"note:{n.id}" for n in notes]
        contents = [n.content for n in notes]
        metadatas = [
            {
                "source": SOURCE_NOTES,
                "date": n.date,
                "time": n.time,
                "tags": ",".join(n.tags),
            }
            for n in notes
        ]

        # Generate embeddings
        try:
            embeddings = await self._embedding_client.embed_batch(contents)
        except Exception as e:
            logger.error(f"Failed to generate embeddings: {e}")
            return

        # Upsert to vector store
        await self._vector_store.upsert_batch(doc_ids, contents, embeddings, metadatas)

    async def search(
        self,
        query: str,
        source: str | None = None,
        category: str | None = None,
        limit: int = 5,
    ) -> list[MemorySearchResult]:
        """Search for relevant memories.

        Args:
            query: Search query text.
            source: Optional source filter ("memories" or "notes").
            category: Optional category filter (for memories only).
            limit: Maximum number of results.

        Returns:
            List of MemorySearchResult objects sorted by relevance.
        """
        # First try sync to ensure index is up to date
        try:
            await self.sync()
        except Exception as e:
            logger.warning(f"Sync failed during search: {e}")

        # Check if embedding is configured
        if not self._embedding_client.is_configured():
            # Fall back to keyword search via in-memory scan
            return await self._keyword_search(query, source, category, limit)

        # Generate query embedding
        try:
            query_embedding = await self._embedding_client.embed(query)
        except Exception as e:
            logger.warning(f"Failed to generate query embedding: {e}, using keyword search")
            return await self._keyword_search(query, source, category, limit)

        # Build metadata filter
        where: dict[str, Any] | None = None
        if source or category:
            where = {}
            if source:
                where["source"] = source
            if category:
                where["category"] = category

        # Search vector store
        results = await self._vector_store.search(
            query_embedding=query_embedding,
            query_text=query,
            limit=limit,
            where=where,
        )

        # Convert to MemorySearchResult
        search_results = []
        for r in results:
            # Convert distance to score (lower distance = higher score)
            # Cosine distance is in [0, 2], convert to [0, 1] score
            score = max(0.0, 1.0 - r.score / 2.0)

            search_results.append(
                MemorySearchResult(
                    content=r.content,
                    source=r.metadata.get("source", ""),
                    category=r.metadata.get("category"),
                    date=r.metadata.get("date"),
                    score=score,
                    metadata=r.metadata,
                )
            )

        return search_results

    async def _keyword_search(
        self,
        query: str,
        source: str | None = None,
        category: str | None = None,
        limit: int = 5,
    ) -> list[MemorySearchResult]:
        """Fall back keyword search when embeddings are not available."""
        results: list[MemorySearchResult] = []

        # Extract query keywords
        query_keywords = self._extract_keywords(query)
        query_lower = query.lower()

        # Search memories
        if source is None or source == SOURCE_MEMORIES:
            memories = await self._load_memories_file()
            for m in memories:
                if category and m.category != category:
                    continue

                score = self._calculate_keyword_score(
                    m.content, m.keywords, query_lower, query_keywords
                )
                if score > 0.1:
                    results.append(
                        MemorySearchResult(
                            content=m.content,
                            source=SOURCE_MEMORIES,
                            category=m.category,
                            date=None,
                            score=score,
                            metadata={"created_at": m.created_at},
                        )
                    )

        # Search notes
        if source is None or source == SOURCE_NOTES:
            note_files = await self._get_all_note_files()
            for filepath in note_files:
                notes = await self._load_notes_file(filepath)
                for n in notes:
                    score = self._calculate_keyword_score(
                        n.content, n.tags, query_lower, query_keywords
                    )
                    if score > 0.1:
                        results.append(
                            MemorySearchResult(
                                content=n.content,
                                source=SOURCE_NOTES,
                                category=None,
                                date=n.date,
                                score=score,
                                metadata={"time": n.time, "tags": n.tags},
                            )
                        )

        # Sort by score and limit
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _extract_keywords(self, text: str) -> set[str]:
        """Extract keywords from text."""
        # Common stop words
        stop_words = {
            "a",
            "an",
            "the",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "of",
            "at",
            "by",
            "for",
            "with",
            "about",
            "to",
            "from",
            "in",
            "out",
            "on",
            "off",
            "and",
            "but",
            "or",
            "if",
            "so",
            "this",
            "that",
            "these",
            "those",
            "it",
            "its",
            "i",
            "me",
            "my",
            "we",
            "our",
            "you",
            "your",
            "he",
            "him",
            "his",
            "she",
            "her",
            "they",
            "them",
            "their",
            "what",
            "which",
            "who",
            "whom",
            "how",
            "when",
            "where",
            "why",
        }

        words = re.findall(r"[\w]+", text.lower())
        return {w for w in words if w not in stop_words and len(w) > 1}

    def _calculate_keyword_score(
        self,
        content: str,
        keywords: list[str],
        query_lower: str,
        query_keywords: set[str],
    ) -> float:
        """Calculate relevance score based on keyword matching."""
        score = 0.0

        content_lower = content.lower()
        content_keywords = self._extract_keywords(content)

        # Exact substring match
        if query_lower in content_lower:
            score += 0.5

        # Keyword overlap
        keyword_set = {k.lower() for k in keywords}
        keyword_overlap = len(query_keywords & keyword_set)
        if query_keywords:
            score += 0.3 * (keyword_overlap / len(query_keywords))

        # Content word overlap
        content_overlap = len(query_keywords & content_keywords)
        if query_keywords:
            score += 0.2 * (content_overlap / len(query_keywords))

        return min(1.0, score)

    # =========================================================================
    # Public API for direct memory management (used by tools)
    # =========================================================================

    async def save_memory(
        self,
        content: str,
        category: str = "fact",
    ) -> Memory:
        """Save a new memory.

        Note: This is a convenience method. The agent can also directly edit
        the memories.yaml file using Edit/Write tools.

        Args:
            content: The content to remember.
            category: Category (decision, preference, fact).

        Returns:
            The created Memory object.
        """
        await self._ensure_dirs()

        # Validate category
        if category not in VALID_CATEGORIES:
            category = "fact"

        # Load existing memories
        memories = await self._load_memories_file()

        # Create new memory
        memory = Memory(
            id=str(uuid.uuid4())[:8],
            content=content,
            category=category,
            created_at=datetime.now().isoformat(),
            source=SOURCE_MEMORIES,
            keywords=list(self._extract_keywords(content))[:10],
        )

        memories.append(memory)

        # Save to file
        await self._save_memories_file(memories)

        # Invalidate file hash to trigger re-index on next sync
        self._file_hashes.pop(self.memories_file, None)

        return memory

    async def _save_memories_file(self, memories: list[Memory]) -> None:
        """Save memories to memories.yaml."""
        await self._ensure_dirs()

        data = {
            "version": self.VERSION,
            "updated_at": datetime.now().isoformat(),
            "memories": [
                {
                    "id": m.id,
                    "content": m.content,
                    "category": m.category,
                    "created_at": m.created_at,
                    "keywords": m.keywords,
                }
                for m in memories
            ],
        }

        yaml_content = yaml.dump(
            data, allow_unicode=True, default_flow_style=False, sort_keys=False
        )

        async with aiofiles.open(self.memories_file, "w", encoding="utf-8") as f:
            await f.write(yaml_content)

    async def list_memories(self, category: str | None = None) -> list[Memory]:
        """List all memories, optionally filtered by category.

        Args:
            category: Optional category filter.

        Returns:
            List of Memory objects.
        """
        memories = await self._load_memories_file()

        if category:
            return [m for m in memories if m.category == category]

        return memories

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory by ID.

        Args:
            memory_id: The ID of the memory to delete.

        Returns:
            True if deleted, False if not found.
        """
        memories = await self._load_memories_file()

        for i, m in enumerate(memories):
            if m.id == memory_id:
                del memories[i]
                await self._save_memories_file(memories)
                # Invalidate file hash
                self._file_hashes.pop(self.memories_file, None)
                return True

        return False

    async def clear_memories(self, category: str | None = None) -> int:
        """Clear memories, optionally only from a specific category.

        Args:
            category: Optional category to clear.

        Returns:
            Number of memories deleted.
        """
        memories = await self._load_memories_file()
        original_count = len(memories)

        memories = [m for m in memories if m.category != category] if category else []
        deleted = original_count - len(memories)

        if deleted > 0:
            await self._save_memories_file(memories)
            # Invalidate file hash
            self._file_hashes.pop(self.memories_file, None)

        return deleted
