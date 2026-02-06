"""LiteLLM embedding client for vector search.

This module provides an async wrapper around LiteLLM's embedding API
for generating text embeddings used in semantic search.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from utils import get_logger

if TYPE_CHECKING:
    from llm.model_manager import ModelManager

logger = get_logger(__name__)

# Default embedding model if not configured
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


class EmbeddingClient:
    """Async client for generating text embeddings via LiteLLM.

    Uses LiteLLM to support multiple embedding providers:
    - OpenAI: text-embedding-3-small, text-embedding-3-large, text-embedding-ada-002
    - Cohere: embed-english-v3.0, embed-multilingual-v3.0
    - Local: Ollama embeddings
    """

    def __init__(
        self,
        model_manager: ModelManager | None = None,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
    ):
        """Initialize the embedding client.

        Args:
            model_manager: Optional ModelManager for getting embedding config.
            model: Embedding model ID (e.g., "text-embedding-3-small").
            api_key: API key for the embedding provider.
            api_base: Custom API base URL.
        """
        self._model_manager = model_manager
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._embedding_dim: int | None = None

    @property
    def model(self) -> str:
        """Get the embedding model ID."""
        if self._model:
            return self._model

        # Try to get from model manager's embedding config
        if self._model_manager:
            config = self._model_manager.get_embedding_config()
            if config and config.get("model"):
                return config["model"]

        return DEFAULT_EMBEDDING_MODEL

    @property
    def api_key(self) -> str | None:
        """Get the API key."""
        if self._api_key:
            return self._api_key

        if self._model_manager:
            config = self._model_manager.get_embedding_config()
            if config and config.get("api_key"):
                return config["api_key"]

        return None

    @property
    def api_base(self) -> str | None:
        """Get the API base URL."""
        if self._api_base:
            return self._api_base

        if self._model_manager:
            config = self._model_manager.get_embedding_config()
            if config and config.get("api_base"):
                return config["api_base"]

        return None

    @property
    def embedding_dim(self) -> int:
        """Get the embedding dimension for the current model."""
        if self._embedding_dim:
            return self._embedding_dim

        # Known dimensions for common models
        model_dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
            "embed-english-v3.0": 1024,
            "embed-multilingual-v3.0": 1024,
        }

        model_name = self.model.split("/")[-1]  # Remove provider prefix if present
        return model_dimensions.get(model_name, 1536)  # Default to 1536

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: The text to embed.

        Returns:
            List of floats representing the embedding vector.

        Raises:
            RuntimeError: If embedding generation fails.
        """
        import litellm

        try:
            # Build kwargs
            kwargs: dict = {"model": self.model, "input": [text]}

            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.api_base:
                kwargs["api_base"] = self.api_base

            # Wrapper to ensure sync call
            def _embed() -> Any:
                return litellm.embedding(**kwargs)

            # Run in thread to avoid blocking
            response = await asyncio.to_thread(_embed)

            embedding: list[float] = response.data[0]["embedding"]

            # Cache the dimension
            if not self._embedding_dim:
                self._embedding_dim = len(embedding)

            return embedding

        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise RuntimeError(f"Failed to generate embedding: {e}") from e

    async def embed_batch(self, texts: list[str], batch_size: int = 100) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.
            batch_size: Maximum batch size for API calls.

        Returns:
            List of embedding vectors.

        Raises:
            RuntimeError: If embedding generation fails.
        """
        import litellm

        if not texts:
            return []

        all_embeddings: list[list[float]] = []

        try:
            # Process in batches
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]

                kwargs: dict = {"model": self.model, "input": batch}

                if self.api_key:
                    kwargs["api_key"] = self.api_key
                if self.api_base:
                    kwargs["api_base"] = self.api_base

                # Wrapper to ensure sync call, capture kwargs to avoid late binding
                def _embed_batch(kw: dict = kwargs) -> Any:
                    return litellm.embedding(**kw)

                response = await asyncio.to_thread(_embed_batch)

                # Extract embeddings in order
                batch_embeddings: list[list[float]] = [item["embedding"] for item in response.data]
                all_embeddings.extend(batch_embeddings)

                # Cache the dimension from first result
                if not self._embedding_dim and batch_embeddings:
                    self._embedding_dim = len(batch_embeddings[0])

            return all_embeddings

        except Exception as e:
            logger.error(f"Batch embedding generation failed: {e}")
            raise RuntimeError(f"Failed to generate batch embeddings: {e}") from e

    def is_configured(self) -> bool:
        """Check if the embedding client is properly configured.

        Returns:
            True if the client has necessary configuration.
        """
        model = self.model

        # Local models (Ollama) don't require API key
        if "ollama" in model.lower():
            return True

        # Check if API key is available
        return bool(self.api_key)
