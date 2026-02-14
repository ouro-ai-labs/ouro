"""ChatGPT (Codex subscription) auth helpers built on top of LiteLLM.

This module keeps OAuth credentials under ``~/.ouro/auth/chatgpt`` and exposes
async helpers for login/logout/status.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import webbrowser
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import aiofiles
import aiofiles.os

from utils.runtime import get_runtime_dir

_AUTH_PROVIDER_ALIASES = {
    "chatgpt": "chatgpt",
    "codex": "chatgpt",
    "openai-codex": "chatgpt",
}

CHATGPT_DEVICE_VERIFY_URL = "https://auth.openai.com/codex/device"
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


def _parse_expires_at(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        with suppress(ValueError):
            return int(float(value))
    return None


async def _should_open_browser_before_login() -> bool:
    """Whether pre-opening browser is likely necessary.

    If auth.json already has a valid access token or any refresh token,
    LiteLLM can usually proceed without a fresh device login.
    """
    data = await _read_json(_get_chatgpt_auth_file_path())
    if not data:
        return True

    if data.get("refresh_token"):
        return False

    access_token = bool(data.get("access_token"))
    if not access_token:
        return True

    expires_at = _parse_expires_at(data.get("expires_at"))
    if expires_at is None:
        # unknown expiry; let authenticator decide without forcing a new browser tab
        return False

    return time.time() >= (expires_at - TOKEN_EXPIRY_SKEW_SECONDS)


def _open_chatgpt_device_page_best_effort() -> bool:
    """Open ChatGPT device-login page if possible.

    Returns:
        True if the browser launch was accepted by the platform handler.
    """
    if os.environ.get("OURO_NO_BROWSER", "").strip().lower() in {"1", "true", "yes"}:
        return False

    with suppress(Exception):
        return bool(webbrowser.open(CHATGPT_DEVICE_VERIFY_URL, new=2))

    return False


def _get_chatgpt_authenticator():
    try:
        import litellm
    except Exception as e:  # pragma: no cover - import error path
        raise RuntimeError(
            "LiteLLM is required for ChatGPT login. Install/upgrade litellm>=1.81.1."
        ) from e

    config_cls = getattr(litellm, "ChatGPTConfig", None)
    if config_cls is None:
        raise RuntimeError(
            "Installed LiteLLM does not support ChatGPT OAuth provider. "
            "Please upgrade to litellm>=1.81.1."
        )

    config = config_cls()
    authenticator = getattr(config, "authenticator", None)
    if authenticator is None:
        raise RuntimeError("LiteLLM ChatGPT authenticator is unavailable.")

    return authenticator


async def login_chatgpt() -> ChatGPTAuthStatus:
    """Run ChatGPT login flow via LiteLLM and return resulting status."""
    await _ensure_auth_dir()

    # Best effort: pre-open device page only when a fresh login is likely required.
    if await _should_open_browser_before_login():
        opened = await asyncio.to_thread(_open_chatgpt_device_page_best_effort)
        if not opened:
            print(  # noqa: T201
                "Could not open browser automatically. Open "
                f"{CHATGPT_DEVICE_VERIFY_URL} manually.",
                flush=True,
            )

    authenticator = await asyncio.to_thread(_get_chatgpt_authenticator)
    await asyncio.to_thread(authenticator.get_access_token)
    await asyncio.to_thread(authenticator.get_account_id)

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
