"""Web fetch tool for retrieving content from URLs."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import socket
import time
from dataclasses import dataclass
from email.message import Message
from typing import Any, TypedDict
from urllib.parse import urljoin, urlparse

import aiofiles
import aiofiles.os
import httpx
import trafilatura
from lxml import html as lxml_html

from .base import BaseTool

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120
MAX_REDIRECTS = 5
ALLOWED_PORTS = {80, 443}
BLOCKED_HOSTS = {"localhost"}
BLOCKED_SUFFIXES = (".local",)
TEXT_CONTENT_TYPES = {"", "text/plain", "text/markdown"}
HTML_STRIP_XPATH = "//script|//style|//noscript|//iframe|//object|//embed"
ACCEPT_HEADERS = {
    "markdown": "text/markdown;q=1.0, text/x-markdown;q=0.9, text/plain;q=0.8, text/html;q=0.7, */*;q=0.1",
    "text": "text/plain;q=1.0, text/markdown;q=0.9, text/html;q=0.8, */*;q=0.1",
    "html": "text/html;q=1.0, application/xhtml+xml;q=0.9, text/plain;q=0.8, text/markdown;q=0.7, */*;q=0.1",
}

# Cache configuration
CACHE_TTL_SECONDS = 300  # 5 minutes TTL
CACHE_MAX_ENTRIES = 100


def _get_encoding_from_headers(headers: httpx.Headers) -> str | None:
    content_type = headers.get("content-type")
    if not content_type:
        return None
    message = Message()
    message["content-type"] = content_type
    charset = message.get_param("charset")
    if not charset:
        return None
    if isinstance(charset, tuple):
        charset = charset[0]
    if not isinstance(charset, str):
        return None
    return charset.strip("'\"")


class ExtractedLink(TypedDict):
    """Structured link extracted from HTML content."""

    href: str
    text: str
    type: str  # "internal", "external", "anchor", "mailto", "tel"


@dataclass
class CacheEntry:
    """Cache entry for URL fetch results."""

    result: dict[str, Any]
    timestamp: float
    ttl: float


class WebFetchCache:
    """Simple in-memory cache for web fetch results."""

    def __init__(self, max_entries: int = CACHE_MAX_ENTRIES):
        self._cache: dict[str, CacheEntry] = {}
        self._max_entries = max_entries

    def _make_key(self, url: str, format: str) -> str:
        """Create a cache key from URL and format."""
        return hashlib.md5(f"{url}:{format}".encode()).hexdigest()

    def get(self, url: str, format: str) -> dict[str, Any] | None:
        """Get cached result if valid."""
        key = self._make_key(url, format)
        entry = self._cache.get(key)
        if entry is None:
            return None
        # Check TTL
        if time.time() - entry.timestamp > entry.ttl:
            del self._cache[key]
            return None
        return entry.result

    def set(
        self, url: str, format: str, result: dict[str, Any], ttl: float = CACHE_TTL_SECONDS
    ) -> None:
        """Cache a result."""
        # Evict oldest entries if at capacity
        if len(self._cache) >= self._max_entries:
            oldest_key = min(self._cache, key=lambda k: self._cache[k].timestamp)
            del self._cache[oldest_key]

        key = self._make_key(url, format)
        self._cache[key] = CacheEntry(result=result, timestamp=time.time(), ttl=ttl)

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()


# Global cache instance
_url_cache = WebFetchCache()


class WebFetchError(Exception):
    """Structured error for WebFetchTool."""

    def __init__(self, code: str, message: str, metadata: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.metadata = metadata or {}


class WebFetchTool(BaseTool):
    """Fetch content from URLs and convert to various formats."""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch content from a URL and convert to markdown, text, or HTML. "
            "Returns JSON with ok/output/metadata or error_code/message. "
            "Use save_to parameter to save content to a local file for later grep/search. "
            "IMPORTANT: When using save_to, the response will NOT contain the actual content - "
            "only a confirmation that the file was saved. You MUST use read_file or grep_content "
            "to access the saved content before using it."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "url": {
                "type": "string",
                "description": "The URL to fetch content from (must start with http:// or https://)",
            },
            "format": {
                "type": "string",
                "enum": ["markdown", "text", "html"],
                "description": "Output format - markdown by default",
                "default": "markdown",
            },
            "timeout": {
                "type": "number",
                "description": "Optional timeout in seconds (max 120)",
                "default": DEFAULT_TIMEOUT_SECONDS,
            },
            "save_to": {
                "type": "string",
                "description": (
                    "Optional file path to save the fetched content. "
                    "Parent directories will be created if needed. "
                    "WARNING: When this parameter is used, the response will only contain "
                    "a save confirmation, NOT the actual content. You MUST call read_file "
                    "or grep_content afterwards to access the content."
                ),
            },
            "use_cache": {
                "type": "boolean",
                "description": (
                    "Whether to use cached results if available (default: true). "
                    "Cache TTL is 5 minutes. Set to false to force a fresh fetch."
                ),
                "default": True,
            },
        }

    async def execute(self, **kwargs) -> str:
        """Execute web fetch with format conversion."""
        url = kwargs.get("url")
        format_value = kwargs.get("format", "markdown")
        timeout = kwargs.get("timeout")
        save_to = kwargs.get("save_to")
        use_cache = kwargs.get("use_cache", True)
        start = time.time()

        try:
            if not url:
                raise WebFetchError("invalid_url", "URL is required", {"requested_url": url})

            # Check cache first (only if use_cache is True and save_to is not specified)
            if use_cache and not save_to:
                cached_result = _url_cache.get(url, format_value)
                if cached_result is not None:
                    # Update metadata to indicate cache hit
                    result = cached_result.copy()
                    result["metadata"] = result.get("metadata", {}).copy()
                    result["metadata"]["cache_hit"] = True
                    result["metadata"]["duration_ms"] = int((time.time() - start) * 1000)
                    return json.dumps(result, ensure_ascii=False)

            result = await self._execute(
                url=url, format=format_value, timeout=timeout, start_time=start, save_to=save_to
            )

            # Cache successful results (only if save_to is not specified)
            if result.get("ok") and not save_to:
                _url_cache.set(url, format_value, result)
                result["metadata"]["cache_hit"] = False

            return json.dumps(result, ensure_ascii=False)
        except WebFetchError as exc:
            error_result = {
                "ok": False,
                "error_code": exc.code,
                "message": exc.message,
                "metadata": exc.metadata,
            }
            return json.dumps(error_result, ensure_ascii=False)
        except Exception as exc:
            error_result = {
                "ok": False,
                "error_code": "unexpected_error",
                "message": str(exc),
                "metadata": {"requested_url": url},
            }
            return json.dumps(error_result, ensure_ascii=False)

    async def _execute(
        self,
        url: str,
        format: str,
        timeout: float | None,
        start_time: float,
        save_to: str | None = None,
    ) -> dict[str, Any]:
        if format not in {"markdown", "text", "html"}:
            raise WebFetchError(
                "invalid_format",
                "Format must be one of markdown, text, or html",
                {"requested_format": format},
            )

        parsed_url = await self._validate_url(url)
        timeout_seconds = (
            DEFAULT_TIMEOUT_SECONDS
            if timeout is None
            else max(1.0, min(float(timeout), MAX_TIMEOUT_SECONDS))
        )

        response, content_bytes, redirects = await self._fetch_with_redirects(
            parsed_url.geturl(), format, timeout_seconds
        )

        content_type_header = response.headers.get("content-type", "")
        content_type = content_type_header.partition(";")[0].strip().lower()
        encoding = (
            _get_encoding_from_headers(response.headers)
            or getattr(response, "encoding", None)
            or getattr(response, "apparent_encoding", None)
            or "utf-8"
        )
        content = content_bytes.decode(encoding, errors="replace")

        output, title = self._convert_content(content, content_type, format, url)

        # Extract structured links from HTML content
        links: list[ExtractedLink] = []
        if "html" in content_type or content_type in {"application/xhtml+xml"}:
            links = self._extract_links(content, str(response.url))

        # Save content to file if save_to is specified
        saved_path = None
        if save_to:
            saved_path = await self._save_content(output, save_to)

        metadata: dict[str, Any] = {
            "requested_url": url,
            "final_url": str(response.url),
            "status_code": response.status_code,
            "content_type": content_type_header,
            "charset": encoding,
            "fetched_bytes": len(content_bytes),
            "output_chars": len(output),
            "redirects": redirects,
            "truncated": len(content_bytes) >= MAX_RESPONSE_BYTES,
            "duration_ms": int((time.time() - start_time) * 1000),
        }

        # Add extracted links to metadata if any were found
        if links:
            metadata["links"] = links

        if saved_path:
            metadata["saved_to"] = saved_path
            # When saved to file, don't include full content in result to save tokens
            # User can access content via read_file or grep_content
            return {
                "ok": True,
                "title": title,
                "output": f"Content saved to: {saved_path}\nUse read_file or grep_content to access the content.",
                "metadata": metadata,
            }

        # Check content size before returning
        estimated_tokens = len(output) // self.CHARS_PER_TOKEN
        if estimated_tokens > self.MAX_TOKENS:
            raise WebFetchError(
                "content_too_large",
                f"Page content (~{estimated_tokens} tokens) exceeds maximum allowed ({self.MAX_TOKENS}). "
                f"Use save_to parameter to save content to a file, then use grep_content to search it.",
                {"estimated_tokens": estimated_tokens, "max_tokens": self.MAX_TOKENS},
            )

        return {
            "ok": True,
            "title": title,
            "output": output,
            "metadata": metadata,
        }

    async def _save_content(self, content: str, save_to: str) -> str:
        """Save content to a file, creating parent directories if needed.

        Args:
            content: Content to save
            save_to: File path to save to

        Returns:
            Absolute path where content was saved
        """
        # Get absolute path
        abs_path = os.path.abspath(save_to)

        # Create parent directories if needed
        parent_dir = os.path.dirname(abs_path)
        if parent_dir:
            await aiofiles.os.makedirs(parent_dir, exist_ok=True)

        # Write content to file
        async with aiofiles.open(abs_path, "w", encoding="utf-8") as f:
            await f.write(content)

        return abs_path

    async def _validate_url(self, url: str):
        if not url.startswith(("http://", "https://")):
            raise WebFetchError(
                "invalid_url",
                "URL must start with http:// or https://",
                {"requested_url": url},
            )

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc or not parsed.hostname:
            raise WebFetchError(
                "invalid_url",
                "URL is missing a valid hostname",
                {"requested_url": url},
            )

        if parsed.username or parsed.password:
            raise WebFetchError(
                "invalid_url",
                "URLs with embedded credentials are not allowed",
                {"requested_url": url},
            )

        host = parsed.hostname.lower()
        if host in BLOCKED_HOSTS or host.endswith(BLOCKED_SUFFIXES):
            raise WebFetchError(
                "blocked_host",
                "Access to localhost or .local domains is not allowed",
                {"host": host},
            )

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in ALLOWED_PORTS:
            raise WebFetchError(
                "blocked_host",
                "Access to the requested port is not allowed",
                {"host": host, "port": port},
            )

        await self._ensure_host_safe(host, port)
        return parsed

    async def _ensure_host_safe(self, host: str, port: int) -> None:
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None

        if ip:
            if not self._is_ip_allowed(ip):
                raise WebFetchError(
                    "blocked_ip",
                    "Access to the requested IP address is not allowed",
                    {"ip": str(ip)},
                )
            return

        resolved_ips = await self._resolve_host(host, port)
        if not resolved_ips:
            raise WebFetchError(
                "dns_error",
                "Failed to resolve hostname",
                {"host": host},
            )

        for resolved in resolved_ips:
            ip_value = ipaddress.ip_address(resolved)
            if not self._is_ip_allowed(ip_value):
                raise WebFetchError(
                    "blocked_ip",
                    "Resolved IP address is not allowed",
                    {"host": host, "ip": str(ip_value)},
                )

    async def _resolve_host(self, host: str, port: int) -> list[str]:
        try:
            loop = asyncio.get_running_loop()
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return []
        addresses = []
        for info in infos:
            sockaddr = info[4]
            if sockaddr:
                addresses.append(str(sockaddr[0]))
        return list(dict.fromkeys(addresses))

    def _is_ip_allowed(self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        if str(ip) == "169.254.169.254":
            return False
        return ip.is_global

    async def _fetch_with_redirects(
        self, url: str, format: str, timeout: float
    ) -> tuple[httpx.Response, bytes, list[str]]:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ouro/1.0)",
            "Accept": ACCEPT_HEADERS.get(format, "*/*"),
            "Accept-Language": "en-US,en;q=0.9",
        }

        redirects: list[str] = []
        current_url = url
        timeout_config = httpx.Timeout(timeout)
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout_config) as client:
            for _ in range(MAX_REDIRECTS + 1):
                parsed = await self._validate_url(current_url)
                try:
                    response, content_bytes = await self._request(
                        client, parsed.geturl(), headers, timeout
                    )
                except httpx.TimeoutException as exc:
                    raise WebFetchError(
                        "timeout",
                        "Request timed out",
                        {"requested_url": current_url},
                    ) from exc
                except httpx.RequestError as exc:
                    raise WebFetchError(
                        "request_error",
                        "Failed to fetch URL",
                        {"requested_url": current_url, "error": str(exc)},
                    ) from exc

                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise WebFetchError(
                            "http_error",
                            "Redirect response missing Location header",
                            {"requested_url": current_url, "status_code": response.status_code},
                        )
                    next_url = urljoin(current_url, location)
                    try:
                        await self._validate_url(next_url)
                    except WebFetchError as exc:
                        raise WebFetchError(
                            "redirect_blocked",
                            "Redirect target is not allowed",
                            {
                                "requested_url": current_url,
                                "redirect_url": next_url,
                                "redirect_error": exc.code,
                            },
                        ) from exc
                    redirects.append(next_url)
                    current_url = next_url
                    continue

                if response.status_code >= 400:
                    raise WebFetchError(
                        "http_error",
                        f"Request failed with status code: {response.status_code}",
                        {"requested_url": current_url, "status_code": response.status_code},
                    )

                return response, content_bytes, redirects

        raise WebFetchError(
            "redirect_blocked",
            "Too many redirects",
            {"requested_url": url, "redirects": redirects},
        )

    async def _request(
        self, client: httpx.AsyncClient, url: str, headers: dict[str, str], timeout: float
    ) -> tuple[httpx.Response, bytes]:
        async with client.stream("GET", url, headers=headers, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                return response, b""
            if response.status_code >= 400:
                return response, b""
            content_bytes = await self._read_response(response)
            return response, content_bytes

    async def _read_response(self, response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_RESPONSE_BYTES:
                    raise WebFetchError(
                        "too_large",
                        "Response too large (exceeds 5MB limit)",
                        {"content_length": int(content_length)},
                    )
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise WebFetchError(
                    "too_large",
                    "Response too large (exceeds 5MB limit)",
                    {"fetched_bytes": total},
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _convert_content(
        self, content: str, content_type: str, format: str, url: str
    ) -> tuple[str, str]:
        if "html" in content_type or content_type in {"application/xhtml+xml"}:
            if format == "html":
                return content, f"{url} ({content_type})"
            return self._render_html(content, format, url)

        if content_type.startswith("text/") or content_type in TEXT_CONTENT_TYPES:
            return content, f"{url} ({content_type or 'text/plain'})"

        if content_type == "application/json":
            try:
                payload = json.loads(content)
                formatted = json.dumps(payload, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                formatted = content
            return formatted, f"{url} ({content_type})"

        raise WebFetchError(
            "unsupported_content_type",
            "Unsupported content type for web fetch",
            {"content_type": content_type},
        )

    def _render_html(self, html: str, format: str, url: str) -> tuple[str, str]:
        # Extract title from HTML
        title = url
        try:
            tree = lxml_html.fromstring(html)
            title_elem = tree.find(".//title")
            if title_elem is not None and title_elem.text:
                title = title_elem.text.strip()
        except Exception:
            pass

        if format == "markdown":
            # Use trafilatura for markdown extraction
            result = trafilatura.extract(
                html,
                include_links=True,
                include_formatting=True,
                include_tables=True,
                output_format="markdown",
            )
            if result:
                return result.strip(), title
            # Fallback: extract as text if markdown fails
            result = trafilatura.extract(html)
            return result.strip() if result else "", title

        # For text format, use trafilatura without formatting
        result = trafilatura.extract(html, include_links=False, include_formatting=False)
        return result.strip() if result else "", title

    def _extract_links(self, html: str, base_url: str, max_links: int = 50) -> list[ExtractedLink]:
        """Extract structured links from HTML content.

        Args:
            html: Raw HTML content
            base_url: Base URL for resolving relative links
            max_links: Maximum number of links to extract (default: 50)

        Returns:
            List of ExtractedLink dictionaries with href, text, and type
        """
        links: list[ExtractedLink] = []
        try:
            tree = lxml_html.fromstring(html)
            parsed_base = urlparse(base_url)
            base_domain = parsed_base.netloc.lower()

            for anchor in tree.iter("a"):
                href = anchor.get("href")
                if not href:
                    continue

                # Get link text (strip whitespace and normalize)
                text = anchor.text_content().strip() if anchor.text_content() else ""
                text = " ".join(text.split())  # Normalize whitespace
                if not text:
                    # Try alt text from child img if no text
                    img = anchor.find(".//img")
                    if img is not None:
                        text = img.get("alt", "").strip()

                # Determine link type
                link_type: str
                if href.startswith("#"):
                    link_type = "anchor"
                elif href.startswith("mailto:"):
                    link_type = "mailto"
                elif href.startswith("tel:"):
                    link_type = "tel"
                elif href.startswith(("javascript:", "data:")):
                    continue  # Skip javascript and data URLs
                else:
                    # Resolve relative URLs
                    resolved_href = urljoin(base_url, href)
                    parsed_href = urlparse(resolved_href)
                    href_domain = parsed_href.netloc.lower()

                    link_type = "internal" if href_domain == base_domain else "external"
                    href = resolved_href

                links.append(ExtractedLink(href=href, text=text[:200], type=link_type))

                if len(links) >= max_links:
                    break

        except Exception:
            # If parsing fails, return empty list
            pass

        return links
