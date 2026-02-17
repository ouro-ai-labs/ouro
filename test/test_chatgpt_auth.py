import json
import sys
import time
import urllib.parse
from asyncio import create_task, sleep
from pathlib import Path
from types import SimpleNamespace

import httpx

from llm.chatgpt_auth import (
    ChatGPTAuthStatus,
    _get_chatgpt_authenticator,
    _prompt_for_redirect_code,
    configure_chatgpt_auth_env,
    get_auth_provider_status,
    get_chatgpt_auth_status,
    is_auth_status_logged_in,
    login_auth_provider,
    login_chatgpt,
    logout_auth_provider,
    logout_chatgpt,
    normalize_auth_provider,
)


def test_normalize_auth_provider_aliases():
    assert normalize_auth_provider(None) == "chatgpt"
    assert normalize_auth_provider("chatgpt") == "chatgpt"
    assert normalize_auth_provider("codex") == "chatgpt"
    assert normalize_auth_provider("openai-codex") == "chatgpt"
    assert normalize_auth_provider("unknown") is None


async def test_get_status_when_auth_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(tmp_path / "chatgpt-auth"))

    status = await get_chatgpt_auth_status()

    assert status.exists is False
    assert status.has_access_token is False
    assert status.account_id is None
    assert status.expired is None


async def test_get_status_and_logout(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))

    auth_file = auth_dir / "auth.json"
    auth_file.write_text(
        json.dumps(
            {
                "access_token": "token-123",
                "account_id": "acct_abc",
                "expires_at": int(time.time()) + 3600,
            }
        ),
        encoding="utf-8",
    )

    status = await get_chatgpt_auth_status()
    assert status.exists is True
    assert status.has_access_token is True
    assert status.account_id == "acct_abc"
    assert status.expired is False

    removed = await logout_chatgpt()
    assert removed is True

    status_after = await get_chatgpt_auth_status()
    assert status_after.exists is False


async def test_login_uses_oauth_flow_by_default(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))

    called = {"oauth": 0, "device": 0}

    async def fake_oauth_login():
        called["oauth"] += 1
        (auth_dir / "auth.json").write_text(
            json.dumps(
                {
                    "access_token": "token-xyz",
                    "refresh_token": "rt_123",
                    "id_token": "id_123",
                    "account_id": "acct_login",
                    "expires_at": int(time.time()) + 120,
                }
            ),
            encoding="utf-8",
        )

    async def fake_device_login():
        called["device"] += 1

    monkeypatch.setattr("llm.chatgpt_auth._login_chatgpt_oauth_via_local_server", fake_oauth_login)
    monkeypatch.setattr(
        "llm.chatgpt_auth._login_chatgpt_via_litellm_device_code", fake_device_login
    )

    status = await login_chatgpt()
    assert called["oauth"] == 1
    assert called["device"] == 0
    assert status.exists is True
    assert status.has_access_token is True
    assert status.account_id == "acct_login"


async def test_login_skips_browser_open_when_refresh_token_exists(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))
    (auth_dir / "auth.json").write_text(
        json.dumps({"refresh_token": "rt_123", "expires_at": int(time.time()) - 10}),
        encoding="utf-8",
    )

    called = {"refreshed": 0, "oauth": 0}

    async def fake_oauth_login():
        called["oauth"] += 1

    async def fake_refresh(token):  # noqa: ARG001
        called["refreshed"] += 1
        return {"access_token": "at_refreshed", "refresh_token": "rt_123", "id_token": "id_123"}

    monkeypatch.setattr("llm.chatgpt_auth._login_chatgpt_oauth_via_local_server", fake_oauth_login)
    monkeypatch.setattr("llm.chatgpt_auth._refresh_chatgpt_tokens", fake_refresh)

    await login_chatgpt()

    assert called["refreshed"] == 1
    assert called["oauth"] == 0


async def test_login_skips_browser_open_when_access_token_is_still_valid(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))
    (auth_dir / "auth.json").write_text(
        json.dumps({"access_token": "at_123", "expires_at": int(time.time()) + 3600}),
        encoding="utf-8",
    )

    called = {"oauth": 0, "refresh": 0}

    async def fake_oauth_login():
        called["oauth"] += 1

    async def fake_refresh(_: str):
        called["refresh"] += 1
        return {"access_token": "x", "refresh_token": "y", "id_token": "z"}

    monkeypatch.setattr("llm.chatgpt_auth._login_chatgpt_oauth_via_local_server", fake_oauth_login)
    monkeypatch.setattr("llm.chatgpt_auth._refresh_chatgpt_tokens", fake_refresh)

    await login_chatgpt()

    assert called["oauth"] == 0
    assert called["refresh"] == 0


async def test_login_skips_browser_open_when_access_token_has_unknown_expiry(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))
    (auth_dir / "auth.json").write_text(
        json.dumps({"access_token": "at_123"}),
        encoding="utf-8",
    )

    called = {"oauth": 0}

    async def fake_oauth_login():
        called["oauth"] += 1

    monkeypatch.setattr("llm.chatgpt_auth._login_chatgpt_oauth_via_local_server", fake_oauth_login)

    await login_chatgpt()

    # Unknown expiry: our login path can't prove validity, so it proceeds with OAuth.
    assert called["oauth"] == 1


async def test_login_opens_browser_when_access_token_is_expired_and_no_refresh(
    tmp_path, monkeypatch
):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))
    (auth_dir / "auth.json").write_text(
        json.dumps({"access_token": "at_123", "expires_at": int(time.time()) - 1}),
        encoding="utf-8",
    )

    called = {"oauth": 0}

    async def fake_oauth_login():
        called["oauth"] += 1
        (auth_dir / "auth.json").write_text(
            json.dumps({"access_token": "new_token", "expires_at": int(time.time()) + 120}),
            encoding="utf-8",
        )

    monkeypatch.setattr("llm.chatgpt_auth._login_chatgpt_oauth_via_local_server", fake_oauth_login)
    await login_chatgpt()

    assert called["oauth"] == 1


async def test_login_opens_browser_when_token_near_expiry_and_no_refresh(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))
    (auth_dir / "auth.json").write_text(
        json.dumps({"access_token": "at_123", "expires_at": int(time.time()) + 30}),
        encoding="utf-8",
    )

    called = {"oauth": 0}

    async def fake_oauth_login():
        called["oauth"] += 1

    monkeypatch.setattr("llm.chatgpt_auth._login_chatgpt_oauth_via_local_server", fake_oauth_login)
    await login_chatgpt()

    assert called["oauth"] == 1


async def test_login_prints_manual_url_when_browser_open_fails(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))
    monkeypatch.setenv("OURO_CHATGPT_OAUTH_TIMEOUT_SECONDS", "5")

    messages: list[str] = []
    monkeypatch.setattr(
        "builtins.print",
        lambda *args, **kwargs: messages.append(" ".join(str(a) for a in args)),
    )

    async def fake_open(_: str) -> bool:
        return False

    async def fake_exchange(**kwargs):  # noqa: ARG001
        return {"access_token": "token-xyz", "refresh_token": "rt_123", "id_token": "id_123"}

    monkeypatch.setattr("llm.chatgpt_auth._open_url_best_effort", fake_open)
    monkeypatch.setattr("llm.chatgpt_auth._exchange_chatgpt_oauth_code_for_tokens", fake_exchange)

    task = create_task(login_chatgpt())
    auth_url = None
    for _ in range(50):
        joined = "\n".join(messages)
        for line in joined.splitlines():
            if line.startswith("https://auth.openai.com/oauth/authorize?"):
                auth_url = line.strip()
                break
        if auth_url:
            break
        await sleep(0.05)
    assert auth_url is not None

    query = urllib.parse.urlparse(auth_url).query
    params = urllib.parse.parse_qs(query)
    redirect_uri = params["redirect_uri"][0]
    state = params["state"][0]

    async with httpx.AsyncClient(timeout=5) as client:
        await client.get(f"{redirect_uri}?code=fake_code&state={state}")

    await task

    assert any("Could not open browser automatically" in msg for msg in messages)
    assert (auth_dir / "auth.json").exists()


async def test_login_can_force_device_code_flow(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))
    monkeypatch.setenv("OURO_CHATGPT_LOGIN_METHOD", "device")

    called = {"device": 0, "oauth": 0}

    async def fake_device_login():
        called["device"] += 1
        (auth_dir / "auth.json").write_text(
            json.dumps({"access_token": "token-device", "expires_at": int(time.time()) + 3600}),
            encoding="utf-8",
        )

    async def fake_oauth_login():
        called["oauth"] += 1

    monkeypatch.setattr(
        "llm.chatgpt_auth._login_chatgpt_via_litellm_device_code", fake_device_login
    )
    monkeypatch.setattr("llm.chatgpt_auth._login_chatgpt_oauth_via_local_server", fake_oauth_login)

    status = await login_chatgpt()

    assert called["device"] == 1
    assert called["oauth"] == 0
    assert status.exists is True
    assert status.has_access_token is True


async def test_prompt_for_redirect_code_accepts_query_string(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "?code=abc123&state=expected")

    code = await _prompt_for_redirect_code(expected_state="expected")
    assert code == "abc123"


async def test_prompt_for_redirect_code_accepts_code_hash_state(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "abc123#expected")

    code = await _prompt_for_redirect_code(expected_state="expected")
    assert code == "abc123"


async def test_prompt_for_redirect_code_accepts_code_equals_hash_state(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "code=abc123#state=expected")

    code = await _prompt_for_redirect_code(expected_state="expected")
    assert code == "abc123"


async def test_prompt_for_redirect_code_rejects_state_mismatch(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "code=abc123&state=wrong")

    try:
        await _prompt_for_redirect_code(expected_state="expected")
    except RuntimeError as exc:
        assert "state mismatch" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("Expected state mismatch error")


async def test_login_falls_back_to_manual_paste_when_callback_bind_fails(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))
    monkeypatch.setenv("OURO_CHATGPT_OAUTH_TIMEOUT_SECONDS", "5")

    messages: list[str] = []
    monkeypatch.setattr(
        "builtins.print",
        lambda *args, **kwargs: messages.append(" ".join(str(a) for a in args)),
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    def fail_bind(*args, **kwargs):  # noqa: ARG001
        raise OSError("bind failed")

    async def fake_open(_: str) -> bool:
        return False

    captured: dict[str, str] = {}

    async def fake_exchange(*, code: str, redirect_uri: str, code_verifier: str) -> dict[str, str]:
        captured.update(
            {"code": code, "redirect_uri": redirect_uri, "code_verifier": code_verifier}
        )
        return {"access_token": "token-xyz", "refresh_token": "rt_123", "id_token": "id_123"}

    def fake_input(_: str) -> str:
        auth_url = None
        for msg in messages:
            for line in msg.splitlines():
                if line.startswith("https://auth.openai.com/oauth/authorize?"):
                    auth_url = line.strip()
                    break
            if auth_url:
                break
        assert auth_url is not None
        params = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
        state = params["state"][0]
        return f"?code=fake_code&state={state}"

    monkeypatch.setattr("llm.chatgpt_auth._start_callback_server", fail_bind)
    monkeypatch.setattr("llm.chatgpt_auth._open_url_best_effort", fake_open)
    monkeypatch.setattr("llm.chatgpt_auth._exchange_chatgpt_oauth_code_for_tokens", fake_exchange)
    monkeypatch.setattr("builtins.input", fake_input)

    status = await login_chatgpt()

    assert captured["code"] == "fake_code"
    assert status.exists is True
    assert (auth_dir / "auth.json").exists()


def test_configure_chatgpt_auth_env_uses_existing(monkeypatch):
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", "/tmp/existing-auth")
    assert configure_chatgpt_auth_env() == "/tmp/existing-auth"


def test_configure_chatgpt_auth_env_normalizes_existing(monkeypatch):
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", "~/tmp-auth")
    expected = str((Path.home() / "tmp-auth").resolve())

    assert configure_chatgpt_auth_env() == expected


def test_configure_chatgpt_auth_env_sets_default(monkeypatch):
    monkeypatch.delenv("CHATGPT_TOKEN_DIR", raising=False)
    monkeypatch.setattr("llm.chatgpt_auth.get_runtime_dir", lambda: "/tmp/ouro-runtime")

    result = configure_chatgpt_auth_env()

    assert result == "/tmp/ouro-runtime/auth/chatgpt"


def test_open_chatgpt_device_page_respects_disable_env(monkeypatch):
    monkeypatch.setenv("OURO_NO_BROWSER", "1")

    opened = False

    def _should_not_open(*args, **kwargs):  # noqa: ARG001
        nonlocal opened
        opened = True
        return True

    monkeypatch.setattr("llm.chatgpt_auth.webbrowser.open", _should_not_open)

    from llm.chatgpt_auth import _open_chatgpt_device_page_best_effort

    assert _open_chatgpt_device_page_best_effort() is False
    assert opened is False


def test_open_chatgpt_device_page_success(monkeypatch):
    monkeypatch.delenv("OURO_NO_BROWSER", raising=False)
    monkeypatch.setattr("llm.chatgpt_auth.webbrowser.open", lambda *args, **kwargs: True)

    from llm.chatgpt_auth import _open_chatgpt_device_page_best_effort

    assert _open_chatgpt_device_page_best_effort() is True


async def test_logout_returns_false_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(tmp_path / "chatgpt-auth"))

    removed = await logout_chatgpt()

    assert removed is False


async def test_get_status_marks_expired_when_expires_at_is_string(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))

    (auth_dir / "auth.json").write_text(
        json.dumps(
            {
                "access_token": "token-123",
                "expires_at": str(int(time.time()) - 10),
            }
        ),
        encoding="utf-8",
    )

    status = await get_chatgpt_auth_status()

    assert status.exists is True
    assert status.expired is True


def test_get_authenticator_raises_when_chatgpt_provider_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace())

    try:
        _get_chatgpt_authenticator()
    except RuntimeError as e:
        assert "does not support ChatGPT OAuth provider" in str(e)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError")


def test_get_authenticator_raises_when_authenticator_missing(monkeypatch):
    class FakeConfig:
        pass

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(ChatGPTConfig=lambda: FakeConfig()),
    )

    try:
        _get_chatgpt_authenticator()
    except RuntimeError as e:
        assert "authenticator is unavailable" in str(e)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError")


async def test_provider_wrappers_reject_unsupported_provider():
    try:
        await get_auth_provider_status("unknown")
    except ValueError as e:
        assert "Unsupported provider" in str(e)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError")

    try:
        await login_auth_provider("unknown")
    except ValueError as e:
        assert "Unsupported provider" in str(e)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError")

    try:
        await logout_auth_provider("unknown")
    except ValueError as e:
        assert "Unsupported provider" in str(e)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError")


def test_is_auth_status_logged_in():
    status = ChatGPTAuthStatus(
        provider="chatgpt",
        auth_file="/tmp/auth.json",
        exists=True,
        has_access_token=True,
        account_id=None,
        expires_at=None,
        expired=None,
    )
    assert is_auth_status_logged_in(status) is True

    status.has_access_token = False
    assert is_auth_status_logged_in(status) is False
