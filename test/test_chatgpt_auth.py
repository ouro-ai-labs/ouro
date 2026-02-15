import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from llm.chatgpt_auth import (
    ChatGPTAuthStatus,
    _get_chatgpt_authenticator,
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


async def test_login_uses_litellm_authenticator(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))
    state = {"opened": 0}

    monkeypatch.setattr(
        "llm.chatgpt_auth._open_chatgpt_device_page_best_effort",
        lambda: state.__setitem__("opened", state["opened"] + 1) or True,
    )

    class FakeAuthenticator:
        def get_access_token(self):
            auth_path = auth_dir / "auth.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "access_token": "token-xyz",
                        "account_id": "acct_login",
                        "expires_at": int(time.time()) + 120,
                    }
                ),
                encoding="utf-8",
            )
            return "token-xyz"

        def get_account_id(self):
            return "acct_login"

    monkeypatch.setattr(
        "llm.chatgpt_auth._get_chatgpt_authenticator",
        lambda: FakeAuthenticator(),
    )

    status = await login_chatgpt()
    assert state["opened"] == 1
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

    state = {"opened": 0}
    monkeypatch.setattr(
        "llm.chatgpt_auth._open_chatgpt_device_page_best_effort",
        lambda: state.__setitem__("opened", state["opened"] + 1) or True,
    )

    class FakeAuthenticator:
        def get_access_token(self):
            return "token-from-refresh"

        def get_account_id(self):
            return None

    monkeypatch.setattr("llm.chatgpt_auth._get_chatgpt_authenticator", lambda: FakeAuthenticator())

    await login_chatgpt()

    assert state["opened"] == 0


async def test_login_skips_browser_open_when_access_token_is_still_valid(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))
    (auth_dir / "auth.json").write_text(
        json.dumps({"access_token": "at_123", "expires_at": int(time.time()) + 3600}),
        encoding="utf-8",
    )

    state = {"opened": 0}
    monkeypatch.setattr(
        "llm.chatgpt_auth._open_chatgpt_device_page_best_effort",
        lambda: state.__setitem__("opened", state["opened"] + 1) or True,
    )

    class FakeAuthenticator:
        def get_access_token(self):
            return "at_123"

        def get_account_id(self):
            return None

    monkeypatch.setattr("llm.chatgpt_auth._get_chatgpt_authenticator", lambda: FakeAuthenticator())

    await login_chatgpt()

    assert state["opened"] == 0


async def test_login_skips_browser_open_when_access_token_has_unknown_expiry(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))
    (auth_dir / "auth.json").write_text(
        json.dumps({"access_token": "at_123"}),
        encoding="utf-8",
    )

    state = {"opened": 0}
    monkeypatch.setattr(
        "llm.chatgpt_auth._open_chatgpt_device_page_best_effort",
        lambda: state.__setitem__("opened", state["opened"] + 1) or True,
    )

    class FakeAuthenticator:
        def get_access_token(self):
            return "at_123"

        def get_account_id(self):
            return None

    monkeypatch.setattr("llm.chatgpt_auth._get_chatgpt_authenticator", lambda: FakeAuthenticator())

    await login_chatgpt()

    assert state["opened"] == 0


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

    state = {"opened": 0}
    monkeypatch.setattr(
        "llm.chatgpt_auth._open_chatgpt_device_page_best_effort",
        lambda: state.__setitem__("opened", state["opened"] + 1) or True,
    )

    class FakeAuthenticator:
        def get_access_token(self):
            return "new_token"

        def get_account_id(self):
            return None

    monkeypatch.setattr("llm.chatgpt_auth._get_chatgpt_authenticator", lambda: FakeAuthenticator())

    await login_chatgpt()

    assert state["opened"] == 1


async def test_login_opens_browser_when_token_near_expiry_and_no_refresh(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))
    (auth_dir / "auth.json").write_text(
        json.dumps({"access_token": "at_123", "expires_at": int(time.time()) + 30}),
        encoding="utf-8",
    )

    state = {"opened": 0}
    monkeypatch.setattr(
        "llm.chatgpt_auth._open_chatgpt_device_page_best_effort",
        lambda: state.__setitem__("opened", state["opened"] + 1) or True,
    )

    class FakeAuthenticator:
        def get_access_token(self):
            return "new_token"

        def get_account_id(self):
            return None

    monkeypatch.setattr("llm.chatgpt_auth._get_chatgpt_authenticator", lambda: FakeAuthenticator())

    await login_chatgpt()

    assert state["opened"] == 1


async def test_login_prints_manual_url_when_browser_open_fails(tmp_path, monkeypatch):
    auth_dir = tmp_path / "chatgpt-auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(auth_dir))

    messages: list[str] = []
    monkeypatch.setattr("llm.chatgpt_auth._open_chatgpt_device_page_best_effort", lambda: False)
    monkeypatch.setattr(
        "builtins.print",
        lambda *args, **kwargs: messages.append(" ".join(str(a) for a in args)),
    )

    class FakeAuthenticator:
        def get_access_token(self):
            (auth_dir / "auth.json").write_text(
                json.dumps({"access_token": "token-xyz"}),
                encoding="utf-8",
            )
            return "token-xyz"

        def get_account_id(self):
            return None

    monkeypatch.setattr(
        "llm.chatgpt_auth._get_chatgpt_authenticator",
        lambda: FakeAuthenticator(),
    )

    await login_chatgpt()

    assert any("Could not open browser automatically" in msg for msg in messages)


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
