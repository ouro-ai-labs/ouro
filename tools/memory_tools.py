"""Memory tools for long-term knowledge persistence.

These tools allow the AI to search long-term memory for relevant information
across sessions. Memory can be saved by directly editing files using Edit/Write tools.

Memory files:
- ~/.aloop/memory/memories.yaml: Core memories (decisions, preferences, facts)
- ~/.aloop/memory/notes/YYYY-MM-DD.yaml: Daily notes
"""

from typing import Any

from memory.long_term import SOURCE_MEMORIES, SOURCE_NOTES, MemoryIndexer

from .base import BaseTool

# Shared instance for tools to use
_memory_indexer: MemoryIndexer | None = None


def get_memory_indexer() -> MemoryIndexer:
    """Get or create the shared MemoryIndexer instance."""
    global _memory_indexer
    if _memory_indexer is None:
        _memory_indexer = MemoryIndexer()
    return _memory_indexer


def set_memory_indexer(indexer: MemoryIndexer) -> None:
    """Set the shared MemoryIndexer instance (for testing/configuration)."""
    global _memory_indexer
    _memory_indexer = indexer


class MemoryRecallTool(BaseTool):
    """Tool for recalling information from long-term memory.

    Use this tool to retrieve previously saved knowledge that may be
    relevant to the current task or conversation.
    """

    @property
    def name(self) -> str:
        return "memory_recall"

    @property
    def description(self) -> str:
        return """Search long-term memory for relevant information.

USE THIS TOOL WHEN:
- Starting a new task (check for relevant preferences/conventions)
- Uncertain about user preferences or project rules
- Need to recall a previous decision or its rationale
- Looking for previously saved reference information

SEARCH TIPS:
- Use descriptive queries with key terms
- Filter by source ("memories" or "notes") if needed
- Filter by category for memories ("decision", "preference", "fact")
- Results are ranked by relevance (semantic similarity)

MEMORY STORAGE:
To save new memories, use the Edit or Write tool to modify:
- ~/.aloop/memory/memories.yaml for core memories
- ~/.aloop/memory/notes/YYYY-MM-DD.yaml for daily notes

Returns memories matching your query, sorted by relevance score."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "query": {
                "type": "string",
                "description": "Search query describing what you're looking for",
            },
            "source": {
                "type": "string",
                "description": 'Optional: filter by source ("memories" or "notes")',
                "default": "",
            },
            "category": {
                "type": "string",
                "description": "Optional: filter by category (decision, preference, fact) - only for memories",
                "default": "",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5)",
                "default": 5,
            },
        }

    async def execute(
        self,
        query: str,
        source: str = "",
        category: str = "",
        limit: int = 5,
    ) -> str:
        """Search long-term memory for relevant information."""
        if not query or not query.strip():
            return "Error: Query cannot be empty."

        indexer = get_memory_indexer()

        # Handle source filter
        source_filter: str | None = None
        if source:
            source_lower = source.strip().lower()
            if source_lower in {SOURCE_MEMORIES, "memory"}:
                source_filter = SOURCE_MEMORIES
            elif source_lower in {SOURCE_NOTES, "note"}:
                source_filter = SOURCE_NOTES

        # Handle category filter (only for memories)
        category_filter: str | None = None
        if category:
            category_lower = category.strip().lower()
            if category_lower in {"decision", "preference", "fact"}:
                category_filter = category_lower

        # Ensure limit is reasonable
        limit = max(1, min(20, limit))

        try:
            results = await indexer.search(
                query=query.strip(),
                source=source_filter,
                category=category_filter,
                limit=limit,
            )
        except Exception as e:
            return f"Error searching memories: {e}"

        if not results:
            return "No relevant memories found."

        # Format results
        output_lines = [f"Found {len(results)} relevant memories:\n"]

        for i, result in enumerate(results, 1):
            # Source indicator
            if result.source == SOURCE_MEMORIES:
                source_str = f"[{result.category or 'memory'}]"
            else:
                source_str = f"[note:{result.date}]"

            # Score as percentage
            score_pct = result.score * 100

            output_lines.append(f"{i}. {source_str} (score: {score_pct:.0f}%)")
            output_lines.append(f"   {result.content}")

            # Additional metadata
            meta_parts = []
            if result.metadata.get("created_at"):
                meta_parts.append(f"created: {result.metadata['created_at'][:10]}")
            if result.metadata.get("time"):
                meta_parts.append(f"time: {result.metadata['time']}")
            if result.metadata.get("tags"):
                tags = result.metadata["tags"]
                if isinstance(tags, str):
                    tags = tags.split(",")
                meta_parts.append(f"tags: {', '.join(tags)}")

            if meta_parts:
                output_lines.append(f"   ({', '.join(meta_parts)})")

            output_lines.append("")

        return "\n".join(output_lines)
