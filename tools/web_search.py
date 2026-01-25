"""Web search tool using DuckDuckGo."""

import asyncio
from typing import Any, Dict, List

from ddgs import DDGS

from .base import BaseTool

# Default timeout for web search operations
DEFAULT_SEARCH_TIMEOUT = 30.0


def _sync_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Synchronous search function to run in thread."""
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


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
            },
            "timeout": {
                "type": "number",
                "description": "Optional timeout in seconds (default: 30)",
                "default": DEFAULT_SEARCH_TIMEOUT,
            },
        }

    async def execute(self, query: str, timeout: float = DEFAULT_SEARCH_TIMEOUT) -> str:
        """Execute web search and return results."""
        try:
            timeout_val = float(timeout) if timeout else DEFAULT_SEARCH_TIMEOUT
            results = []
            async with asyncio.timeout(timeout_val):
                search_results = await asyncio.to_thread(_sync_search, query, 5)
                for r in search_results:
                    title = r.get("title", "")
                    href = r.get("href", "")
                    body = r.get("body", "")
                    results.append(f"[{title}]({href})\n{body}\n")
            return "\n---\n".join(results) if results else "No results found"
        except TimeoutError:
            return f"Error: Web search timed out after {timeout}s"
        except Exception as e:
            return f"Error searching web: {str(e)}"
