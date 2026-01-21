"""Web fetch tool for retrieving content from URLs."""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from lxml import html as lxml_html
from requests.utils import get_encoding_from_headers

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


class WebFetchError(Exception):
    """Structured error for WebFetchTool."""

    def __init__(self, code: str, message: str, metadata: Optional[Dict[str, Any]] = None):
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
            "Use save_to parameter to save content to a local file for later grep/search."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
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
                    "Useful for saving content to search later with grep_content."
                ),
            },
        }

    def execute(self, **kwargs) -> str:
        """Execute web fetch with format conversion."""
        url = kwargs.get("url")
        format_value = kwargs.get("format", "markdown")
        timeout = kwargs.get("timeout")
        save_to = kwargs.get("save_to")
        start = time.time()

        try:
            if not url:
                raise WebFetchError("invalid_url", "URL is required", {"requested_url": url})
            result = self._execute(
                url=url, format=format_value, timeout=timeout, start_time=start, save_to=save_to
            )
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

    def _execute(
        self,
        url: str,
        format: str,
        timeout: Optional[float],
        start_time: float,
        save_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        if format not in {"markdown", "text", "html"}:
            raise WebFetchError(
                "invalid_format",
                "Format must be one of markdown, text, or html",
                {"requested_format": format},
            )

        parsed_url = self._validate_url(url)
        timeout_seconds = (
            DEFAULT_TIMEOUT_SECONDS
            if timeout is None
            else max(1.0, min(float(timeout), MAX_TIMEOUT_SECONDS))
        )

        response, redirects = self._fetch_with_redirects(
            parsed_url.geturl(), format, timeout_seconds
        )

        content_type_header = response.headers.get("content-type", "")
        content_type = content_type_header.partition(";")[0].strip().lower()
        content_bytes = self._read_response(response)
        encoding = (
            get_encoding_from_headers(response.headers)
            or response.encoding
            or response.apparent_encoding
            or "utf-8"
        )
        content = content_bytes.decode(encoding, errors="replace")

        output, title = self._convert_content(content, content_type, format, url)

        # Save content to file if save_to is specified
        saved_path = None
        if save_to:
            saved_path = self._save_content(output, save_to)

        metadata = {
            "requested_url": url,
            "final_url": response.url,
            "status_code": response.status_code,
            "content_type": content_type_header,
            "charset": encoding,
            "fetched_bytes": len(content_bytes),
            "output_chars": len(output),
            "redirects": redirects,
            "truncated": len(content_bytes) >= MAX_RESPONSE_BYTES,
            "duration_ms": int((time.time() - start_time) * 1000),
        }

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

        return {
            "ok": True,
            "title": title,
            "output": output,
            "metadata": metadata,
        }

    def _save_content(self, content: str, save_to: str) -> str:
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
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        # Write content to file
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)

        return abs_path

    def _validate_url(self, url: str):
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

        self._ensure_host_safe(host, port)
        return parsed

    def _ensure_host_safe(self, host: str, port: int) -> None:
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

        resolved_ips = self._resolve_host(host, port)
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

    def _resolve_host(self, host: str, port: int) -> List[str]:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return []
        addresses = []
        for info in infos:
            sockaddr = info[4]
            if sockaddr:
                addresses.append(str(sockaddr[0]))
        return list(dict.fromkeys(addresses))

    def _is_ip_allowed(self, ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]) -> bool:
        if str(ip) == "169.254.169.254":
            return False
        return ip.is_global

    def _fetch_with_redirects(
        self, url: str, format: str, timeout: float
    ) -> Tuple[requests.Response, List[str]]:
        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AgenticLoop/1.0)",
            "Accept": ACCEPT_HEADERS.get(format, "*/*"),
            "Accept-Language": "en-US,en;q=0.9",
        }

        redirects: List[str] = []
        current_url = url
        for _ in range(MAX_REDIRECTS + 1):
            parsed = self._validate_url(current_url)
            try:
                response = self._request(session, parsed.geturl(), headers, timeout)
            except requests.Timeout as exc:
                raise WebFetchError(
                    "timeout",
                    "Request timed out",
                    {"requested_url": current_url},
                ) from exc
            except requests.RequestException as exc:
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
                    self._validate_url(next_url)
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

            return response, redirects

        raise WebFetchError(
            "redirect_blocked",
            "Too many redirects",
            {"requested_url": url, "redirects": redirects},
        )

    def _request(
        self, session: requests.Session, url: str, headers: Dict[str, str], timeout: float
    ) -> requests.Response:
        return session.get(
            url, headers=headers, timeout=timeout, stream=True, allow_redirects=False
        )

    def _read_response(self, response: requests.Response) -> bytes:
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

        chunks: List[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
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
    ) -> Tuple[str, str]:
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

    def _render_html(self, html: str, format: str, url: str) -> Tuple[str, str]:
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
