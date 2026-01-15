"""Web search tool using DuckDuckGo."""

from typing import Any, Dict

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover
    DDGS = None  # type: ignore[assignment]

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

    def execute(self, query: str) -> str:
        """Execute web search and return results."""
        if DDGS is None:
            return "Error: Search dependency missing (ddgs). Reinstall dependencies."

        try:
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=5):
                    results.append(f"[{r['title']}]({r['href']})\n{r['body']}\n")
            return "\n---\n".join(results) if results else "No results found"
        except Exception as e:
            return f"Error searching web: {str(e)}"
