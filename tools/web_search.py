"""Web search tool using DuckDuckGo."""

from typing import Any, Dict

from duckduckgo_search import AsyncDDGS

from .base import BaseTool


class WebSearchTool(BaseTool):
    """Simple web search using DuckDuckGo (no API key needed)."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Search the web for information using DuckDuckGo"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "query": {
                "type": "string",
                "description": "Search query",
            }
        }

    async def execute(self, query: str) -> str:
        """Execute web search and return results."""
        try:
            results = []
            async with AsyncDDGS() as ddgs_client:
                for r in await ddgs_client.text(query, max_results=5):
                    title = r.get("title", "")
                    href = r.get("href", "")
                    body = r.get("body", "")
                    results.append(f"[{title}]({href})\n{body}\n")
            return "\n---\n".join(results) if results else "No results found"
        except Exception as e:
            return f"Error searching web: {str(e)}"
