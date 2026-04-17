"""GitHub Copilot subscription auth helpers (LiteLLM-compatible token layout).

This module keeps Copilot OAuth credentials under ``~/.ouro/auth/copilot`` and
mirrors the on-disk format LiteLLM's `github_copilot` provider expects:

- ``access-token``: plain-text GitHub OAuth access token (from device flow).
- ``api-key.json``: short-lived Copilot API key + endpoints map.

At request time LiteLLM's Authenticator auto-refreshes ``api-key.json`` from the
access token, so we only need to establish (and persist) the GitHub access token
here. Pointing ``GITHUB_COPILOT_TOKEN_DIR`` at our directory makes LiteLLM read
and write those files in-place.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import aiofiles
import aiofiles.os
import httpx

from utils.runtime import get_runtime_dir

GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_COPILOT_API_KEY_URL = "https://api.github.com/copilot_internal/v2/token"
GITHUB_OAUTH_SCOPE = "read:user"

COPILOT_DEFAULT_POLL_INTERVAL_SECONDS = 5
COPILOT_DEFAULT_POLL_ATTEMPTS = 60  # 5 min @ 5s
COPILOT_HTTP_TIMEOUT_SECONDS = 30
COPILOT_ERROR_BODY_LIMIT = 2000


@dataclass
class CopilotAuthStatus:
    provider: str
    auth_file: str
    exists: bool
    has_access_token: bool
    account_id: str | None
    expires_at: int | None
    expired: bool | None


class CopilotLoginRequiredError(RuntimeError):
    """Raised when a non-interactive caller needs user login."""


def _normalize_token_dir(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path.strip()))


def configure_copilot_auth_env() -> str:
    """Configure Copilot auth dir for LiteLLM and return it.

    LiteLLM's ``github_copilot`` authenticator reads ``GITHUB_COPILOT_TOKEN_DIR``
    to locate the access-token / api-key files on disk. Point it at ouro's own
    runtime dir so local state stays under ``~/.ouro/auth/copilot``.
    """
    token_dir = os.environ.get("GITHUB_COPILOT_TOKEN_DIR")
    if token_dir and token_dir.strip():
        normalized = _normalize_token_dir(token_dir)
        os.environ["GITHUB_COPILOT_TOKEN_DIR"] = normalized
        return normalized

    token_dir = _normalize_token_dir(os.path.join(get_runtime_dir(), "auth", "copilot"))
    os.environ["GITHUB_COPILOT_TOKEN_DIR"] = token_dir
    return token_dir


def _get_access_token_path() -> str:
    token_dir = configure_copilot_auth_env()
    filename = os.environ.get("GITHUB_COPILOT_ACCESS_TOKEN_FILE", "access-token")
    return os.path.join(token_dir, filename)


def _get_api_key_path() -> str:
    token_dir = configure_copilot_auth_env()
    filename = os.environ.get("GITHUB_COPILOT_API_KEY_FILE", "api-key.json")
    return os.path.join(token_dir, filename)


async def _ensure_auth_dir() -> None:
    token_dir = configure_copilot_auth_env()
    await aiofiles.os.makedirs(token_dir, exist_ok=True)
    with suppress(OSError):
        await asyncio.to_thread(os.chmod, token_dir, 0o700)


async def _path_exists(path: str) -> bool:
    try:
        await aiofiles.os.stat(path)
        return True
    except FileNotFoundError:
        return False


async def _read_text(path: str) -> str | None:
    if not await _path_exists(path):
        return None
    try:
        async with aiofiles.open(path, encoding="utf-8") as f:
            return (await f.read()).strip()
    except OSError:
        return None


async def _write_text(path: str, content: str) -> None:
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(content)
    with suppress(OSError):
        await asyncio.to_thread(os.chmod, path, 0o600)


async def _read_json(path: str) -> dict[str, Any] | None:
    text = await _read_text(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _parse_expires_at(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        with suppress(ValueError):
            return int(float(value))
    return None


def _copilot_user_agent() -> str:
    return "ouro/1.0 (github-copilot)"


def _github_headers(access_token: str | None = None) -> dict[str, str]:
    headers = {
        "accept": "application/json",
        "editor-version": "vscode/1.95.0",
        "editor-plugin-version": "copilot-chat/0.26.7",
        "user-agent": _copilot_user_agent(),
        "accept-encoding": "gzip,deflate,br",
        "content-type": "application/json",
    }
    if access_token:
        headers["authorization"] = f"token {access_token}"
    return headers


def _get_http_timeout_seconds() -> float:
    raw = (os.environ.get("OURO_COPILOT_HTTP_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return float(COPILOT_HTTP_TIMEOUT_SECONDS)
    with suppress(ValueError):
        value = float(raw)
        if value > 0:
            return value
    return float(COPILOT_HTTP_TIMEOUT_SECONDS)


def _http_error_details(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    if response is None:
        return str(exc)
    status = response.status_code
    body = ""
    with suppress(Exception):
        body = (response.text or "").strip()
    if len(body) > COPILOT_ERROR_BODY_LIMIT:
        body = body[:COPILOT_ERROR_BODY_LIMIT] + "…"
    return f"HTTP {status}: {body}" if body else f"HTTP {status}"


async def _request_device_code() -> dict[str, Any]:
    timeout = httpx.Timeout(_get_http_timeout_seconds())
    async with httpx.AsyncClient(timeout=timeout, headers=_github_headers()) as client:
        try:
            resp = await client.post(
                GITHUB_DEVICE_CODE_URL,
                json={"client_id": GITHUB_CLIENT_ID, "scope": GITHUB_OAUTH_SCOPE},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Copilot device code request failed: {_http_error_details(exc)}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Copilot device code request failed: {exc}") from exc

        data = resp.json()

    required = ("device_code", "user_code", "verification_uri")
    missing = [f for f in required if not data.get(f)]
    if missing:
        raise RuntimeError(f"Device code response missing fields: {', '.join(missing)}")
    return data


async def _poll_for_github_access_token(
    *, device_code: str, interval: int, max_attempts: int
) -> str:
    timeout = httpx.Timeout(_get_http_timeout_seconds())
    async with httpx.AsyncClient(timeout=timeout, headers=_github_headers()) as client:
        for _ in range(max_attempts):
            try:
                resp = await client.post(
                    GITHUB_ACCESS_TOKEN_URL,
                    json={
                        "client_id": GITHUB_CLIENT_ID,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"Copilot token poll failed: {_http_error_details(exc)}"
                ) from exc
            except httpx.RequestError as exc:
                raise RuntimeError(f"Copilot token poll failed: {exc}") from exc

            body = resp.json()
            access_token = body.get("access_token")
            if isinstance(access_token, str) and access_token:
                return access_token

            error = body.get("error")
            if error == "authorization_pending":
                await asyncio.sleep(interval)
                continue
            if error == "slow_down":
                interval = min(interval + 5, 60)
                await asyncio.sleep(interval)
                continue
            if error in {"access_denied", "expired_token"}:
                raise RuntimeError(f"Copilot login aborted: {error}")
            if error:
                raise RuntimeError(f"Copilot login error: {error}")

            await asyncio.sleep(interval)

    raise RuntimeError("Timed out waiting for the user to authorize the device.")


async def _fetch_copilot_api_key(access_token: str) -> dict[str, Any]:
    """Exchange a GitHub access token for a Copilot API key record.

    Also persists the record at ``api-key.json`` so LiteLLM's authenticator can
    reuse it on subsequent calls without a round-trip.
    """
    timeout = httpx.Timeout(_get_http_timeout_seconds())
    async with httpx.AsyncClient(
        timeout=timeout, headers=_github_headers(access_token)
    ) as client:
        try:
            resp = await client.get(GITHUB_COPILOT_API_KEY_URL)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Copilot API key request failed: {_http_error_details(exc)}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Copilot API key request failed: {exc}") from exc

        data = resp.json()

    if not isinstance(data, dict) or not data.get("token"):
        raise RuntimeError("Copilot API key response missing token.")

    await _write_text(_get_api_key_path(), json.dumps(data))
    return data


async def _run_device_code_login(
    *,
    interval: int = COPILOT_DEFAULT_POLL_INTERVAL_SECONDS,
    max_attempts: int = COPILOT_DEFAULT_POLL_ATTEMPTS,
) -> str:
    """Run the GitHub device code flow and persist the access token.

    Returns the GitHub access token (also written to ``access-token``).
    """
    device = await _request_device_code()
    user_code = device["user_code"]
    verification_uri = device["verification_uri"]
    interval = int(device.get("interval") or interval)

    print(  # noqa: T201
        "To authorize Copilot, visit "
        f"{verification_uri} and enter code {user_code}.\n"
        "Waiting for authorization (Ctrl+C to cancel)...",
        flush=True,
    )

    access_token = await _poll_for_github_access_token(
        device_code=device["device_code"], interval=interval, max_attempts=max_attempts
    )
    await _write_text(_get_access_token_path(), access_token)

    # Warm the Copilot API key record so the first completion call doesn't stall
    # waiting for LiteLLM to synchronously refresh.
    with suppress(Exception):
        await _fetch_copilot_api_key(access_token)

    return access_token


async def ensure_copilot_access_token(*, interactive: bool) -> str:
    """Ensure a GitHub access token exists on disk for LiteLLM.

    Unlike the ChatGPT flow, GitHub OAuth device tokens do not include a refresh
    token: once the access token is revoked, the user must re-run login. This
    helper only triggers the device-code flow when no token is present.
    """
    await _ensure_auth_dir()
    access_token = await _read_text(_get_access_token_path())
    if access_token:
        return access_token

    if not interactive:
        raise CopilotLoginRequiredError("GitHub Copilot is not logged in.")

    return await _run_device_code_login()


async def login_copilot() -> CopilotAuthStatus:
    """Run the GitHub device code flow for Copilot and return status."""
    await _ensure_auth_dir()
    await _run_device_code_login()
    return await get_copilot_auth_status()


async def logout_copilot() -> bool:
    """Remove persisted Copilot credentials. Returns True if something was removed."""
    removed_any = False
    for path in (_get_access_token_path(), _get_api_key_path()):
        if await _path_exists(path):
            await aiofiles.os.remove(path)
            removed_any = True
    return removed_any


async def get_copilot_auth_status() -> CopilotAuthStatus:
    """Inspect local Copilot auth state."""
    await _ensure_auth_dir()
    access_token = await _read_text(_get_access_token_path())
    api_key = await _read_json(_get_api_key_path())

    exists = bool(access_token) or bool(api_key)
    has_access_token = bool(access_token)
    expires_at = _parse_expires_at((api_key or {}).get("expires_at"))
    expired = None if expires_at is None else time.time() >= expires_at

    return CopilotAuthStatus(
        provider="copilot",
        auth_file=_get_access_token_path(),
        exists=exists,
        has_access_token=has_access_token,
        account_id=None,
        expires_at=expires_at,
        expired=expired,
    )
