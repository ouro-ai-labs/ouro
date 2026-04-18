import json
import time
from pathlib import Path

import httpx
import pytest

from llm.chatgpt_auth import (
    get_all_auth_provider_statuses,
    get_auth_provider_status,
    get_supported_auth_providers,
    is_auth_status_logged_in,
    login_auth_provider,
    logout_auth_provider,
    normalize_auth_provider,
)
from llm.copilot_auth import (
    CopilotAuthStatus,
    CopilotLoginRequiredError,
    _fetch_copilot_api_key,
    _get_access_token_path,
    _get_api_key_path,
    _poll_for_github_access_token,
    configure_copilot_auth_env,
    ensure_copilot_access_token,
    get_copilot_auth_status,
    login_copilot,
    logout_copilot,
)


def _seed_auth_dir(monkeypatch, tmp_path) -> Path:
    auth_dir = tmp_path / "copilot-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GITHUB_COPILOT_TOKEN_DIR", str(auth_dir))
    return auth_dir


def test_normalize_auth_provider_includes_copilot():
    assert normalize_auth_provider("copilot") == "copilot"
    assert normalize_auth_provider("github") == "copilot"
    assert normalize_auth_provider("github-copilot") == "copilot"
    assert normalize_auth_provider("github_copilot") == "copilot"


def test_get_supported_auth_providers_lists_copilot():
    providers = get_supported_auth_providers()
    assert "copilot" in providers
    assert "chatgpt" in providers


def test_configure_copilot_auth_env_uses_runtime_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_COPILOT_TOKEN_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    # get_runtime_dir reads HOME at call time via os.path.expanduser
    monkeypatch.setattr("llm.copilot_auth.get_runtime_dir", lambda: str(tmp_path / ".ouro"))

    token_dir = configure_copilot_auth_env()

    assert token_dir.endswith("auth/copilot")
    assert token_dir.startswith(str(tmp_path))


def test_configure_copilot_auth_env_honors_override(tmp_path, monkeypatch):
    override = str(tmp_path / "custom")
    monkeypatch.setenv("GITHUB_COPILOT_TOKEN_DIR", override)

    token_dir = configure_copilot_auth_env()

    assert token_dir == override


async def test_get_status_when_auth_file_missing(tmp_path, monkeypatch):
    _seed_auth_dir(monkeypatch, tmp_path)

    status = await get_copilot_auth_status()

    assert isinstance(status, CopilotAuthStatus)
    assert status.provider == "copilot"
    assert status.exists is False
    assert status.has_access_token is False
    assert status.expired is None


async def test_get_status_from_existing_tokens(tmp_path, monkeypatch):
    auth_dir = _seed_auth_dir(monkeypatch, tmp_path)
    (auth_dir / "access-token").write_text("gh_access_xyz", encoding="utf-8")
    (auth_dir / "api-key.json").write_text(
        json.dumps({"token": "ck_abc", "expires_at": int(time.time()) + 1800}),
        encoding="utf-8",
    )

    status = await get_copilot_auth_status()

    assert status.exists is True
    assert status.has_access_token is True
    assert status.expired is False
    assert is_auth_status_logged_in(status)


async def test_get_status_reports_expired(tmp_path, monkeypatch):
    auth_dir = _seed_auth_dir(monkeypatch, tmp_path)
    (auth_dir / "access-token").write_text("gh_access_xyz", encoding="utf-8")
    (auth_dir / "api-key.json").write_text(
        json.dumps({"token": "ck_abc", "expires_at": int(time.time()) - 60}),
        encoding="utf-8",
    )

    status = await get_copilot_auth_status()

    assert status.has_access_token is True
    assert status.expired is True


async def test_logout_removes_token_files(tmp_path, monkeypatch):
    auth_dir = _seed_auth_dir(monkeypatch, tmp_path)
    (auth_dir / "access-token").write_text("gh_access_xyz", encoding="utf-8")
    (auth_dir / "api-key.json").write_text(json.dumps({"token": "ck_abc"}), encoding="utf-8")

    removed = await logout_copilot()

    assert removed is True
    assert not (auth_dir / "access-token").exists()
    assert not (auth_dir / "api-key.json").exists()

    # Idempotent: second logout reports nothing to remove.
    assert await logout_copilot() is False


async def test_ensure_access_token_reuses_existing_file(tmp_path, monkeypatch):
    auth_dir = _seed_auth_dir(monkeypatch, tmp_path)
    (auth_dir / "access-token").write_text("gh_access_existing", encoding="utf-8")

    called = {"login": 0}

    async def fake_login(**_kwargs):
        called["login"] += 1
        return "should-not-run"

    monkeypatch.setattr("llm.copilot_auth._run_device_code_login", fake_login)

    token = await ensure_copilot_access_token(interactive=False)

    assert token == "gh_access_existing"
    assert called["login"] == 0


async def test_ensure_access_token_non_interactive_requires_login(tmp_path, monkeypatch):
    _seed_auth_dir(monkeypatch, tmp_path)

    with pytest.raises(CopilotLoginRequiredError):
        await ensure_copilot_access_token(interactive=False)


async def test_login_runs_device_code_flow_and_persists_token(tmp_path, monkeypatch):
    auth_dir = _seed_auth_dir(monkeypatch, tmp_path)
    called = {"login": 0}

    async def fake_login(**_kwargs):
        called["login"] += 1
        (auth_dir / "access-token").write_text("gh_access_new", encoding="utf-8")
        return "gh_access_new"

    monkeypatch.setattr("llm.copilot_auth._run_device_code_login", fake_login)

    status = await login_copilot()

    assert called["login"] == 1
    assert status.exists is True
    assert status.has_access_token is True
    assert Path(_get_access_token_path()).read_text(encoding="utf-8") == "gh_access_new"


async def test_provider_dispatch_routes_copilot(tmp_path, monkeypatch):
    _seed_auth_dir(monkeypatch, tmp_path)

    async def fake_login(**_kwargs):
        auth_file = Path(_get_access_token_path())
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        auth_file.write_text("gh_dispatch_token", encoding="utf-8")
        return "gh_dispatch_token"

    monkeypatch.setattr("llm.copilot_auth._run_device_code_login", fake_login)

    status = await login_auth_provider("copilot")
    assert isinstance(status, CopilotAuthStatus)

    status_via_alias = await get_auth_provider_status("github")
    assert isinstance(status_via_alias, CopilotAuthStatus)
    assert status_via_alias.has_access_token is True

    removed = await logout_auth_provider("copilot")
    assert removed is True


async def test_get_all_auth_provider_statuses_includes_copilot(tmp_path, monkeypatch):
    _seed_auth_dir(monkeypatch, tmp_path)
    # Also isolate chatgpt state so the test doesn't see real logins.
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(tmp_path / "chatgpt-auth"))

    statuses = await get_all_auth_provider_statuses()

    assert set(statuses.keys()) == {"chatgpt", "copilot"}
    assert statuses["copilot"].provider == "copilot"
    assert statuses["copilot"].exists is False


async def test_poll_honors_slow_down_and_returns_token(tmp_path, monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("llm.copilot_auth.asyncio.sleep", fake_sleep)

    responses = [
        httpx.Response(200, json={"error": "authorization_pending"}),
        httpx.Response(200, json={"error": "slow_down"}),
        httpx.Response(200, json={"access_token": "gh_polled"}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return responses.pop(0)

    transport = httpx.MockTransport(handler)

    async def fake_async_client(*args, **kwargs):  # noqa: ARG001
        return httpx.AsyncClient(
            transport=transport, **{k: v for k, v in kwargs.items() if k != "transport"}
        )

    # Patch httpx.AsyncClient constructor used inside _poll_for_github_access_token.
    original = httpx.AsyncClient

    class _PatchedClient(original):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("llm.copilot_auth.httpx.AsyncClient", _PatchedClient)

    token = await _poll_for_github_access_token(device_code="dev_123", interval=1, max_attempts=5)

    assert token == "gh_polled"
    # At least one authorization_pending + one slow_down wait.
    assert len(sleeps) >= 2


async def test_fetch_copilot_api_key_writes_record(tmp_path, monkeypatch):
    _seed_auth_dir(monkeypatch, tmp_path)

    expected_record = {
        "token": "ck_from_github",
        "expires_at": int(time.time()) + 1800,
        "endpoints": {"api": "https://api.githubcopilot.com"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "token gh_access"
        return httpx.Response(200, json=expected_record)

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    class _PatchedClient(original):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("llm.copilot_auth.httpx.AsyncClient", _PatchedClient)

    record = await _fetch_copilot_api_key("gh_access")

    assert record["token"] == expected_record["token"]
    on_disk = json.loads(Path(_get_api_key_path()).read_text(encoding="utf-8"))
    assert on_disk["token"] == expected_record["token"]
