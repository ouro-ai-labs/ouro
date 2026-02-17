"""ChatGPT (Codex subscription) auth helpers (LiteLLM-compatible token layout).

This module keeps OAuth credentials under ``~/.ouro/auth/chatgpt`` and exposes
async helpers for login/logout/status.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from contextlib import suppress
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

import aiofiles
import aiofiles.os
import httpx

from utils.runtime import get_runtime_dir

_AUTH_PROVIDER_ALIASES = {
    "chatgpt": "chatgpt",
    "codex": "chatgpt",
    "openai-codex": "chatgpt",
}

CHATGPT_OAUTH_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
CHATGPT_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CHATGPT_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CHATGPT_OAUTH_REDIRECT_HOST = "localhost"
CHATGPT_OAUTH_REDIRECT_PATH = "/auth/callback"
CHATGPT_OAUTH_DEFAULT_CALLBACK_PORT = 1455
CHATGPT_OAUTH_SCOPES = "openid profile email offline_access"
CHATGPT_OAUTH_DEFAULT_TIMEOUT_SECONDS = 10 * 60
CHATGPT_OAUTH_HTTP_TIMEOUT_SECONDS = 30
CHATGPT_OAUTH_ERROR_BODY_LIMIT = 2000
TOKEN_EXPIRY_SKEW_SECONDS = 60


@dataclass
class ChatGPTAuthStatus:
    provider: str
    auth_file: str
    exists: bool
    has_access_token: bool
    account_id: str | None
    expires_at: int | None
    expired: bool | None


def normalize_auth_provider(provider: str | None) -> str | None:
    """Normalize provider aliases for auth commands.

    Returns:
        Canonical provider ID, or None if unsupported.
    """
    if provider is None:
        return "chatgpt"
    return _AUTH_PROVIDER_ALIASES.get(provider.strip().lower())


def get_supported_auth_providers() -> tuple[str, ...]:
    return ("chatgpt",)


def is_auth_status_logged_in(status: ChatGPTAuthStatus) -> bool:
    """Whether local auth state looks usable for requests."""
    return status.exists and status.has_access_token


class ChatGPTAuthenticator(Protocol):
    async def get_access_token(self) -> str: ...

    async def get_account_id(self) -> str | None: ...


def _normalize_token_dir(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path.strip()))


def configure_chatgpt_auth_env() -> str:
    """Configure ChatGPT auth dir for LiteLLM and return it."""
    token_dir = os.environ.get("CHATGPT_TOKEN_DIR")
    if token_dir and token_dir.strip():
        normalized = _normalize_token_dir(token_dir)
        os.environ["CHATGPT_TOKEN_DIR"] = normalized
        return normalized

    token_dir = _normalize_token_dir(os.path.join(get_runtime_dir(), "auth", "chatgpt"))
    os.environ["CHATGPT_TOKEN_DIR"] = token_dir
    return token_dir


def _get_chatgpt_auth_file_path() -> str:
    token_dir = configure_chatgpt_auth_env()
    filename = os.environ.get("CHATGPT_AUTH_FILE", "auth.json")
    return os.path.join(token_dir, filename)


async def _ensure_auth_dir() -> None:
    token_dir = configure_chatgpt_auth_env()
    await aiofiles.os.makedirs(token_dir, exist_ok=True)
    with suppress(OSError):
        await asyncio.to_thread(os.chmod, token_dir, 0o700)


async def _path_exists(path: str) -> bool:
    try:
        await aiofiles.os.stat(path)
        return True
    except FileNotFoundError:
        return False


async def _read_json(path: str) -> dict[str, Any] | None:
    if not await _path_exists(path):
        return None

    try:
        async with aiofiles.open(path, encoding="utf-8") as f:
            content = await f.read()
        data = json.loads(content)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


async def _write_json(path: str, data: dict[str, Any]) -> None:
    content = json.dumps(data)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(content)
    with suppress(OSError):
        await asyncio.to_thread(os.chmod, path, 0o600)


def _parse_expires_at(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        with suppress(ValueError):
            return int(float(value))
    return None


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        data = json.loads(payload_bytes.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _get_expires_at_from_access_token(access_token: str | None) -> int | None:
    if not access_token:
        return None
    exp = _decode_jwt_claims(access_token).get("exp")
    if isinstance(exp, (int, float)):
        return int(exp)
    return None


def _extract_account_id_from_token(token: str | None) -> str | None:
    if not token:
        return None
    auth_claims = _decode_jwt_claims(token).get("https://api.openai.com/auth")
    if isinstance(auth_claims, dict):
        account_id = auth_claims.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
    return None


async def _persist_account_id_if_missing(account_id: str | None) -> None:
    if not account_id:
        return
    auth_file = _get_chatgpt_auth_file_path()
    data = await _read_json(auth_file) or {}
    if data.get("account_id"):
        return
    data["account_id"] = account_id
    await _write_json(auth_file, data)


async def _get_account_id_from_auth_file() -> str | None:
    auth_file = _get_chatgpt_auth_file_path()
    data = await _read_json(auth_file) or {}
    account_id = data.get("account_id")
    if isinstance(account_id, str) and account_id:
        return account_id

    id_token = data.get("id_token") if isinstance(data.get("id_token"), str) else None
    access_token = data.get("access_token") if isinstance(data.get("access_token"), str) else None
    derived = _extract_account_id_from_token(id_token) or _extract_account_id_from_token(
        access_token
    )
    await _persist_account_id_if_missing(derived)
    return derived


def _is_access_token_valid(access_token: str | None, expires_at: int | None) -> bool:
    if not access_token or expires_at is None:
        return False
    return time.time() < (expires_at - TOKEN_EXPIRY_SKEW_SECONDS)


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    with suppress(ValueError):
        return ipaddress.ip_address(host).is_loopback
    return False


def _format_host_for_url(host: str) -> str:
    # RFC 3986: IPv6 literals must be bracketed.
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        return f"[{host}]"
    return host


def _query_param_first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    value = values[0]
    return value if value else None


async def _prompt_for_redirect_code(*, expected_state: str) -> str:
    if not sys.stdin.isatty():
        raise RuntimeError(
            "Timed out waiting for the localhost OAuth callback, and stdin is not a TTY. "
            "Re-run login in an interactive terminal, or use SSH port-forwarding for the callback port."
        )

    raw = await asyncio.to_thread(
        input,
        "Paste the full redirect URL from your browser (or just the `code`): ",
    )
    text = (raw or "").strip()
    if not text:
        raise RuntimeError("No redirect URL/code provided.")

    if text.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(text)
        query = urllib.parse.parse_qs(parsed.query)
        fragment = urllib.parse.parse_qs(parsed.fragment)
        params = {**query, **fragment}

        error = _query_param_first(params, "error")
        if error:
            desc = _query_param_first(params, "error_description") or ""
            raise RuntimeError(f"OAuth error: {error} {desc}".strip())

        code = _query_param_first(params, "code")
        state = _query_param_first(params, "state")
        if state and state != expected_state:
            raise RuntimeError("Redirect URL state mismatch.")
        if not code:
            raise RuntimeError("Redirect URL missing `code` parameter.")
        return code

    if text.startswith(("?", "#")) or any(key in text for key in ("code=", "state=", "error=")):
        left, sep, right = text.partition("#")
        left_params = urllib.parse.parse_qs(left.lstrip("?#"))
        right_params = urllib.parse.parse_qs(right.lstrip("?#")) if sep else {}
        params = {**left_params, **right_params}

        error = _query_param_first(params, "error")
        if error:
            desc = _query_param_first(params, "error_description") or ""
            raise RuntimeError(f"OAuth error: {error} {desc}".strip())

        code = _query_param_first(params, "code")
        state = _query_param_first(params, "state")
        if state and state != expected_state:
            raise RuntimeError("Redirect code state mismatch.")
        if not code:
            raise RuntimeError("Missing authorization code.")
        return code

    if "#" in text:
        code, state = text.split("#", 1)
        code = code.strip()
        state = state.strip()
        if state and state != expected_state:
            raise RuntimeError("Redirect code state mismatch.")
        if not code:
            raise RuntimeError("Missing authorization code.")
        return code

    return text


def _get_chatgpt_oauth_authorize_url() -> str:
    override = (os.environ.get("OURO_CHATGPT_OAUTH_AUTHORIZE_URL") or "").strip()
    return override or CHATGPT_OAUTH_AUTHORIZE_URL


def _get_chatgpt_oauth_token_url() -> str:
    override = (os.environ.get("OURO_CHATGPT_OAUTH_TOKEN_URL") or "").strip()
    return override or CHATGPT_OAUTH_TOKEN_URL


def _get_chatgpt_user_agent() -> str:
    override = (os.environ.get("OURO_CHATGPT_USER_AGENT") or "").strip()
    if override:
        return override
    # Keep this stable and low-entropy; enterprise proxies sometimes fingerprint UA.
    return "Mozilla/5.0 (compatible; ouro/1.0)"


def _chatgpt_default_headers() -> dict[str, str]:
    return {
        "User-Agent": _get_chatgpt_user_agent(),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _get_chatgpt_http_timeout_seconds() -> float:
    raw = (os.environ.get("OURO_CHATGPT_OAUTH_HTTP_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return float(CHATGPT_OAUTH_HTTP_TIMEOUT_SECONDS)
    with suppress(ValueError):
        value = float(raw)
        if value > 0:
            return value
    return float(CHATGPT_OAUTH_HTTP_TIMEOUT_SECONDS)


def _http_error_details(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    if response is None:
        return str(exc)
    status = response.status_code
    body = ""
    with suppress(Exception):
        body = (response.text or "").strip()
    if len(body) > CHATGPT_OAUTH_ERROR_BODY_LIMIT:
        body = body[:CHATGPT_OAUTH_ERROR_BODY_LIMIT] + "…"
    return f"HTTP {status}: {body}" if body else f"HTTP {status}"


def _oauth_client(*, redirect_uri: str):
    try:
        from authlib.integrations.httpx_client import AsyncOAuth2Client
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Authlib is required for browser-based ChatGPT login.") from e

    timeout = httpx.Timeout(_get_chatgpt_http_timeout_seconds())
    return AsyncOAuth2Client(
        client_id=CHATGPT_OAUTH_CLIENT_ID,
        redirect_uri=redirect_uri,
        scope=CHATGPT_OAUTH_SCOPES,
        timeout=timeout,
        follow_redirects=False,
        headers=_chatgpt_default_headers(),
        token_endpoint_auth_method="none",
    )


def _pick_unused_port(host: str) -> int:
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def _start_callback_server(
    host: str, port: int, handler_cls: type[BaseHTTPRequestHandler]
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    httpd = ThreadingHTTPServer((host, port), handler_cls)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


async def _refresh_chatgpt_tokens(refresh_token: str) -> dict[str, str]:
    token_url = _get_chatgpt_oauth_token_url()
    client = _oauth_client(redirect_uri="http://127.0.0.1/unused")
    try:
        try:
            data = await client.refresh_token(token_url, refresh_token=refresh_token)
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"ChatGPT token refresh failed: {_http_error_details(exc)}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"ChatGPT token refresh request failed: {exc}") from exc
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"ChatGPT token refresh failed: {exc}") from exc
    finally:
        with suppress(Exception):
            await client.aclose()

    access_token = data.get("access_token")
    id_token = data.get("id_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError(f"Refresh response missing access_token: {data}")
    if not isinstance(id_token, str) or not id_token:
        raise RuntimeError(f"Refresh response missing id_token: {data}")

    next_refresh_token = data.get("refresh_token")
    if not isinstance(next_refresh_token, str) or not next_refresh_token:
        next_refresh_token = refresh_token

    return {
        "access_token": access_token,
        "refresh_token": next_refresh_token,
        "id_token": id_token,
    }


def _build_auth_record(tokens: dict[str, str]) -> dict[str, Any]:
    access_token = tokens.get("access_token")
    id_token = tokens.get("id_token")
    expires_at = _get_expires_at_from_access_token(access_token)
    account_id = _extract_account_id_from_token(id_token) or _extract_account_id_from_token(
        access_token
    )
    return {
        "access_token": access_token,
        "refresh_token": tokens.get("refresh_token"),
        "id_token": id_token,
        "expires_at": expires_at,
        "account_id": account_id,
    }


def _generate_pkce_verifier() -> str:
    """Generate a PKCE code verifier using Authlib helpers."""
    try:
        from authlib.common.security import generate_token
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Authlib is required for browser-based ChatGPT login.") from e

    verifier = generate_token(96)
    if len(verifier) < 43:
        verifier = (verifier + generate_token(64))[:128]
    return verifier[:128]


async def _open_url_best_effort(url: str) -> bool:
    if os.environ.get("OURO_NO_BROWSER", "").strip().lower() in {"1", "true", "yes"}:
        return False
    with suppress(Exception):
        return bool(await asyncio.to_thread(webbrowser.open, url, new=2))
    return False


async def _exchange_chatgpt_oauth_code_for_tokens(
    *, code: str, redirect_uri: str, code_verifier: str
) -> dict[str, str]:
    token_url = _get_chatgpt_oauth_token_url()
    client = _oauth_client(redirect_uri=redirect_uri)
    try:
        try:
            data = await client.fetch_token(
                token_url,
                code=code,
                grant_type="authorization_code",
                code_verifier=code_verifier,
            )
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"ChatGPT token exchange failed: {_http_error_details(exc)}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"ChatGPT token exchange request failed: {exc}") from exc
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"ChatGPT token exchange failed: {exc}") from exc
    finally:
        with suppress(Exception):
            await client.aclose()

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    id_token = data.get("id_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError(f"Token exchange response missing access_token: {data}")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RuntimeError(f"Token exchange response missing refresh_token: {data}")
    if not isinstance(id_token, str) or not id_token:
        raise RuntimeError(f"Token exchange response missing id_token: {data}")
    return {"access_token": access_token, "refresh_token": refresh_token, "id_token": id_token}


async def _login_chatgpt_oauth_via_local_server() -> None:
    """Run OAuth+PKCE login and persist resulting tokens to auth.json."""
    loop = asyncio.get_running_loop()
    result: asyncio.Future[str] = loop.create_future()

    code_verifier = _generate_pkce_verifier()
    try:
        from authlib.common.security import generate_token
        from authlib.oauth2.rfc7636 import create_s256_code_challenge
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Authlib is required for browser-based ChatGPT login.") from e

    state = generate_token(24)
    code_challenge = create_s256_code_challenge(code_verifier)

    host = (os.environ.get("OURO_CHATGPT_OAUTH_CALLBACK_HOST") or "127.0.0.1").strip()
    allow_non_loopback = (
        (os.environ.get("OURO_CHATGPT_OAUTH_ALLOW_NON_LOOPBACK") or "").strip().lower()
    )
    if allow_non_loopback not in {"1", "true", "yes"} and not _is_loopback_host(host):
        raise RuntimeError(
            "Refusing to bind OAuth callback server to a non-loopback address. "
            "Set `OURO_CHATGPT_OAUTH_CALLBACK_HOST` to `127.0.0.1` (recommended), or set "
            "`OURO_CHATGPT_OAUTH_ALLOW_NON_LOOPBACK=1` if you understand the risks."
        )
    port_raw = (os.environ.get("OURO_CHATGPT_OAUTH_CALLBACK_PORT") or "").strip()
    port = int(port_raw) if port_raw else CHATGPT_OAUTH_DEFAULT_CALLBACK_PORT

    def _set_result(code: str) -> None:
        if not result.done():
            result.set_result(code)

    def _set_exception(exc: Exception) -> None:
        if not result.done():
            result.set_exception(exc)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_text(self, status_code: int, text: str) -> None:
            body = text.encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)

            if parsed.path == CHATGPT_OAUTH_REDIRECT_PATH:
                got_state = _query_param_first(params, "state")
                if got_state != state:
                    self._send_text(400, "Invalid state.")
                    return

                error = _query_param_first(params, "error")
                if error:
                    description = _query_param_first(params, "error_description") or ""
                    loop.call_soon_threadsafe(
                        _set_exception,
                        RuntimeError(f"OAuth error: {error} {description}".strip()),
                    )
                    self._send_text(200, "Sign-in failed. You can close this tab.")
                    return

                code = _query_param_first(params, "code")
                if not code:
                    self._send_text(400, "Missing code.")
                    return

                loop.call_soon_threadsafe(_set_result, code)
                self._send_text(
                    200,
                    "Sign-in complete. You can close this tab and return to the terminal.",
                )
                return

            if parsed.path == "/auth/cancel":
                loop.call_soon_threadsafe(_set_exception, RuntimeError("OAuth login cancelled."))
                self._send_text(200, "Cancelled. You can close this tab.")
                return

            self._send_text(404, "Not found.")

    httpd = None
    thread = None
    bind_error: Exception | None = None
    bound_port = port
    try:
        httpd, thread = _start_callback_server(host, port, Handler)
        bound_port = int(httpd.server_address[1])
    except OSError as exc:
        # If a fixed port is in use, retry with an ephemeral port.
        bind_error = exc
        if port != 0:
            try:
                httpd, thread = _start_callback_server(host, 0, Handler)
                bound_port = int(httpd.server_address[1])
                bind_error = None
            except OSError as exc2:
                bind_error = exc2
        if bind_error is not None:
            # No callback server available; pick a random high port to minimize the chance we
            # redirect to an unrelated local service. We'll fall back to manual paste.
            with suppress(Exception):
                bound_port = await asyncio.to_thread(_pick_unused_port, host)

    try:
        redirect_uri = (
            f"http://{CHATGPT_OAUTH_REDIRECT_HOST}:{bound_port}{CHATGPT_OAUTH_REDIRECT_PATH}"
        )
        client = _oauth_client(redirect_uri=redirect_uri)
        try:
            auth_url, returned_state = client.create_authorization_url(
                _get_chatgpt_oauth_authorize_url(),
                state=state,
                code_challenge=code_challenge,
                code_challenge_method="S256",
                # Mirrors Codex CLI parameters; benign if ignored by the auth service.
                codex_cli_simplified_flow="true",
                id_token_add_organizations="true",
                originator=(
                    os.environ.get("OURO_CHATGPT_OAUTH_ORIGINATOR") or "codex_cli_rs"
                ).strip(),
            )
            state = returned_state
        finally:
            with suppress(Exception):
                await client.aclose()

        opened = await _open_url_best_effort(auth_url)
        if not opened:
            if bind_error is None:
                print(  # noqa: T201
                    "Could not open browser automatically. Open this URL manually:\n"
                    f"{auth_url}\n\n"
                    "If you are running on a remote machine, port-forward the callback server:\n"
                    f"  ssh -L {bound_port}:{host}:{bound_port} <host>\n",
                    flush=True,
                )
            else:
                print(  # noqa: T201
                    "Could not open browser automatically. Open this URL manually:\n"
                    f"{auth_url}\n",
                    flush=True,
                )

        if bind_error is not None:
            print(  # noqa: T201
                "Could not start the localhost OAuth callback server. After you sign in, your browser may show a "
                "connection error; copy the redirect URL from the address bar and paste it here.",
                flush=True,
            )

        timeout_raw = (os.environ.get("OURO_CHATGPT_OAUTH_TIMEOUT_SECONDS") or "").strip()
        timeout_seconds = int(timeout_raw) if timeout_raw else CHATGPT_OAUTH_DEFAULT_TIMEOUT_SECONDS
        if bind_error is not None:
            code = await _prompt_for_redirect_code(expected_state=state)
        else:
            try:
                code = await asyncio.wait_for(result, timeout=timeout_seconds)
            except TimeoutError:
                code = await _prompt_for_redirect_code(expected_state=state)

        tokens = await _exchange_chatgpt_oauth_code_for_tokens(
            code=code, redirect_uri=redirect_uri, code_verifier=code_verifier
        )
        record = _build_auth_record(tokens)
        await _write_json(_get_chatgpt_auth_file_path(), record)
    finally:
        if httpd is not None:
            with suppress(Exception):
                await asyncio.to_thread(httpd.shutdown)
            with suppress(Exception):
                httpd.server_close()
        if thread is not None:
            with suppress(Exception):
                await asyncio.to_thread(thread.join, 1)


class _AuthlibOAuthAuthenticator:
    async def get_access_token(self) -> str:
        await _ensure_auth_dir()
        auth_file = _get_chatgpt_auth_file_path()
        data = await _read_json(auth_file) or {}

        access_token = (
            data.get("access_token") if isinstance(data.get("access_token"), str) else None
        )
        expires_at = _parse_expires_at(data.get("expires_at")) or _get_expires_at_from_access_token(
            access_token
        )
        if expires_at is not None and data.get("expires_at") != expires_at:
            data["expires_at"] = expires_at
            await _write_json(auth_file, data)

        if _is_access_token_valid(access_token, expires_at):
            return access_token  # type: ignore[return-value]

        refresh_token = (
            data.get("refresh_token") if isinstance(data.get("refresh_token"), str) else None
        )
        if refresh_token:
            tokens = await _refresh_chatgpt_tokens(refresh_token)
            record = _build_auth_record(tokens)
            await _write_json(auth_file, record)
            return record["access_token"]

        await _login_chatgpt_oauth_via_local_server()
        data_after = await _read_json(auth_file) or {}
        token_after = data_after.get("access_token")
        if not isinstance(token_after, str) or not token_after:
            raise RuntimeError("ChatGPT OAuth login did not produce an access token.")
        return token_after

    async def get_account_id(self) -> str | None:
        return await _get_account_id_from_auth_file()


async def login_chatgpt() -> ChatGPTAuthStatus:
    """Ensure ChatGPT OAuth credentials exist and return resulting status.

    Uses a browser-based OAuth (PKCE) flow with a localhost callback server, with
    a manual paste fallback when the callback cannot be reached.
    """
    await _ensure_auth_dir()

    authenticator: ChatGPTAuthenticator = _AuthlibOAuthAuthenticator()
    await authenticator.get_access_token()
    await authenticator.get_account_id()
    return await get_chatgpt_auth_status()


async def logout_chatgpt() -> bool:
    """Remove persisted ChatGPT OAuth credentials.

    Returns:
        True if an auth file was removed, False otherwise.
    """
    auth_file = _get_chatgpt_auth_file_path()
    if not await _path_exists(auth_file):
        return False

    await aiofiles.os.remove(auth_file)
    return True


async def get_chatgpt_auth_status() -> ChatGPTAuthStatus:
    """Inspect local ChatGPT auth state."""
    await _ensure_auth_dir()
    auth_file = _get_chatgpt_auth_file_path()
    data = await _read_json(auth_file)

    exists = data is not None
    has_access_token = bool((data or {}).get("access_token"))
    account_id = (data or {}).get("account_id")
    account_id = str(account_id) if account_id else None

    expires_at = _parse_expires_at((data or {}).get("expires_at"))
    expired = None if expires_at is None else time.time() >= expires_at

    return ChatGPTAuthStatus(
        provider="chatgpt",
        auth_file=auth_file,
        exists=exists,
        has_access_token=has_access_token,
        account_id=account_id,
        expires_at=expires_at,
        expired=expired,
    )


async def get_auth_provider_status(provider: str) -> ChatGPTAuthStatus:
    """Get auth status for a supported provider."""
    normalized = normalize_auth_provider(provider)
    if not normalized:
        raise ValueError(f"Unsupported provider: {provider}")

    if normalized == "chatgpt":
        return await get_chatgpt_auth_status()

    raise ValueError(f"Unsupported provider: {provider}")


async def get_all_auth_provider_statuses() -> dict[str, ChatGPTAuthStatus]:
    """Get auth statuses for all supported providers."""
    statuses: dict[str, ChatGPTAuthStatus] = {}
    for provider in get_supported_auth_providers():
        statuses[provider] = await get_auth_provider_status(provider)
    return statuses


async def login_auth_provider(provider: str) -> ChatGPTAuthStatus:
    """Login to a supported provider."""
    normalized = normalize_auth_provider(provider)
    if not normalized:
        raise ValueError(f"Unsupported provider: {provider}")

    if normalized == "chatgpt":
        return await login_chatgpt()

    raise ValueError(f"Unsupported provider: {provider}")


async def logout_auth_provider(provider: str) -> bool:
    """Logout from a supported provider."""
    normalized = normalize_auth_provider(provider)
    if not normalized:
        raise ValueError(f"Unsupported provider: {provider}")

    if normalized == "chatgpt":
        return await logout_chatgpt()

    raise ValueError(f"Unsupported provider: {provider}")
