import json
import sys
import time
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
    assert status.exists is True
    assert status.has_access_token is True
    assert status.account_id == "acct_login"


def test_configure_chatgpt_auth_env_uses_existing(monkeypatch):
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", "/tmp/existing-auth")
    assert configure_chatgpt_auth_env() == "/tmp/existing-auth"


def test_configure_chatgpt_auth_env_sets_default(monkeypatch):
    monkeypatch.delenv("CHATGPT_TOKEN_DIR", raising=False)
    monkeypatch.setattr("llm.chatgpt_auth.get_runtime_dir", lambda: "/tmp/ouro-runtime")

    result = configure_chatgpt_auth_env()

    assert result == "/tmp/ouro-runtime/auth/chatgpt"


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
