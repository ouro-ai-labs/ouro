"""Web search tool using DuckDuckGo."""
from typing import Dict, Any

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
        try:
            # Try new package name first
            try:
                from ddgs import DDGS
            except ImportError:
                # Fallback to old package name
                from duckduckgo_search import DDGS

            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=5):
                    results.append(f"[{r['title']}]({r['href']})\n{r['body']}\n")

            return (
                "\n---\n".join(results) if results else "No results found"
            )
        except ImportError:
            return "Error: Search package not installed. Run: pip install ddgs"
        except Exception as e:
            return f"Error searching web: {str(e)}"
