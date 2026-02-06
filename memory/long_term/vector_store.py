"""ChromaDB vector store for long-term memory.

This module provides a wrapper around ChromaDB for storing and searching
memory embeddings with both vector similarity and full-text search.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from utils import get_logger

logger = get_logger(__name__)

# Collection name for memories
COLLECTION_NAME = "aloop_memories"


@dataclass
class SearchResult:
    """A search result from the vector store."""

    doc_id: str
    content: str
    metadata: dict[str, Any]
    score: float  # Distance score (lower is better for cosine)


class VectorStore:
    """ChromaDB vector store with support for vector and full-text search.

    Stores document embeddings in ChromaDB and provides:
    - Vector similarity search
    - Full-text search (via ChromaDB's built-in support)
    - Metadata filtering
    - Hybrid search combining vector and text matching
    """

    def __init__(self, storage_dir: str, embedding_dim: int = 1536):
        """Initialize the vector store.

        Args:
            storage_dir: Directory for ChromaDB persistent storage.
            embedding_dim: Dimension of embedding vectors.
        """
        self._storage_dir = storage_dir
        self._embedding_dim = embedding_dim
        self._client: Any = None
        self._collection: Any = None
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Ensure ChromaDB client and collection are initialized."""
        if self._initialized:
            return

        import chromadb
        from chromadb.config import Settings

        # Create storage directory if needed
        db_path = os.path.join(self._storage_dir, "vector_db")
        os.makedirs(db_path, exist_ok=True)

        # Initialize ChromaDB with persistent storage
        def _create_client() -> Any:
            return chromadb.PersistentClient(
                path=db_path,
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )

        self._client = await asyncio.to_thread(_create_client)

        # Get or create collection
        def _get_collection() -> Any:
            return self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},  # Use cosine similarity
            )

        self._collection = await asyncio.to_thread(_get_collection)

        self._initialized = True
        logger.debug(f"Initialized ChromaDB at {db_path}")

    async def upsert(
        self,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> None:
        """Insert or update a document.

        Args:
            doc_id: Unique document identifier.
            content: Document text content.
            embedding: Embedding vector.
            metadata: Document metadata (source, category, etc.).
        """
        await self._ensure_initialized()

        # Ensure metadata values are primitive types (ChromaDB requirement)
        clean_metadata = self._clean_metadata(metadata)

        await asyncio.to_thread(
            self._collection.upsert,
            ids=[doc_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[clean_metadata],
        )

    async def upsert_batch(
        self,
        doc_ids: list[str],
        contents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Insert or update multiple documents.

        Args:
            doc_ids: List of document IDs.
            contents: List of document contents.
            embeddings: List of embedding vectors.
            metadatas: List of metadata dicts.
        """
        if not doc_ids:
            return

        await self._ensure_initialized()

        # Clean metadata
        clean_metadatas = [self._clean_metadata(m) for m in metadatas]

        await asyncio.to_thread(
            self._collection.upsert,
            ids=doc_ids,
            embeddings=embeddings,
            documents=contents,
            metadatas=clean_metadatas,
        )

    async def delete(self, doc_id: str) -> None:
        """Delete a document by ID.

        Args:
            doc_id: Document identifier to delete.
        """
        await self._ensure_initialized()

        await asyncio.to_thread(self._collection.delete, ids=[doc_id])

    async def delete_batch(self, doc_ids: list[str]) -> None:
        """Delete multiple documents by ID.

        Args:
            doc_ids: List of document IDs to delete.
        """
        if not doc_ids:
            return

        await self._ensure_initialized()

        await asyncio.to_thread(self._collection.delete, ids=doc_ids)

    async def delete_by_metadata(self, where: dict[str, Any]) -> int:
        """Delete documents matching metadata filter.

        Args:
            where: ChromaDB where filter.

        Returns:
            Number of documents deleted.
        """
        await self._ensure_initialized()

        # First get matching IDs
        results = await asyncio.to_thread(
            self._collection.get,
            where=where,
            include=[],
        )

        if results["ids"]:
            await asyncio.to_thread(self._collection.delete, ids=results["ids"])
            return len(results["ids"])

        return 0

    async def search(
        self,
        query_embedding: list[float],
        query_text: str | None = None,
        limit: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Search for similar documents.

        Args:
            query_embedding: Query embedding vector for similarity search.
            query_text: Optional query text for hybrid search.
            limit: Maximum number of results.
            where: Optional metadata filter.

        Returns:
            List of SearchResult objects sorted by relevance.
        """
        await self._ensure_initialized()

        kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": limit,
            "include": ["documents", "metadatas", "distances"],
        }

        if where:
            kwargs["where"] = where

        # If query_text is provided, also use it for filtering
        if query_text:
            kwargs["where_document"] = {"$contains": query_text.lower()[:50]}

        try:
            results = await asyncio.to_thread(self._collection.query, **kwargs)
        except Exception:
            # Fallback without text filter if it fails
            kwargs.pop("where_document", None)
            results = await asyncio.to_thread(self._collection.query, **kwargs)

        # Convert to SearchResult objects
        search_results: list[SearchResult] = []

        if results["ids"] and results["ids"][0]:
            ids = results["ids"][0]
            documents = results["documents"][0] if results["documents"] else [""] * len(ids)
            metadatas = results["metadatas"][0] if results["metadatas"] else [{}] * len(ids)
            distances = results["distances"][0] if results["distances"] else [1.0] * len(ids)

            for i, doc_id in enumerate(ids):
                search_results.append(
                    SearchResult(
                        doc_id=doc_id,
                        content=documents[i] if i < len(documents) else "",
                        metadata=metadatas[i] if i < len(metadatas) else {},
                        score=distances[i] if i < len(distances) else 1.0,
                    )
                )

        return search_results

    async def get(self, doc_id: str) -> SearchResult | None:
        """Get a document by ID.

        Args:
            doc_id: Document identifier.

        Returns:
            SearchResult if found, None otherwise.
        """
        await self._ensure_initialized()

        results = await asyncio.to_thread(
            self._collection.get,
            ids=[doc_id],
            include=["documents", "metadatas"],
        )

        if results["ids"]:
            return SearchResult(
                doc_id=results["ids"][0],
                content=results["documents"][0] if results["documents"] else "",
                metadata=results["metadatas"][0] if results["metadatas"] else {},
                score=0.0,
            )

        return None

    async def count(self, where: dict[str, Any] | None = None) -> int:
        """Count documents, optionally filtered.

        Args:
            where: Optional metadata filter.

        Returns:
            Number of documents.
        """
        await self._ensure_initialized()

        if where:
            results = await asyncio.to_thread(
                self._collection.get,
                where=where,
                include=[],
            )
            return len(results["ids"])

        return await asyncio.to_thread(self._collection.count)

    async def clear(self) -> None:
        """Clear all documents from the store."""
        await self._ensure_initialized()

        # Delete and recreate collection
        def _delete_collection() -> None:
            self._client.delete_collection(COLLECTION_NAME)

        await asyncio.to_thread(_delete_collection)

        def _recreate_collection() -> Any:
            return self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )

        self._collection = await asyncio.to_thread(_recreate_collection)

    def _clean_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Clean metadata for ChromaDB compatibility.

        ChromaDB only supports str, int, float, bool values.

        Args:
            metadata: Raw metadata dict.

        Returns:
            Cleaned metadata dict.
        """
        clean = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)):
                clean[key] = value
            elif isinstance(value, list):
                # Convert list to comma-separated string
                clean[key] = ",".join(str(v) for v in value)
            elif value is None:
                continue  # Skip None values
            else:
                # Convert to string
                clean[key] = str(value)
        return clean
