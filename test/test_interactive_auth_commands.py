import asyncio
from types import SimpleNamespace

import interactive
from interactive import InteractiveSession
from llm.chatgpt_auth import ChatGPTAuthStatus


class _DummyConsole:
    def __init__(self):
        self.lines: list[str] = []

    def print(self, *args, **kwargs):  # noqa: ARG002
        self.lines.append(" ".join(str(a) for a in args))


class _FakeAgent:
    def __init__(self):
        self.model_manager = SimpleNamespace(
            config_path="/tmp/models.yaml",
            get_current_model=lambda: None,
        )
        self.memory = SimpleNamespace(get_stats=lambda: {})

    def switch_model(self, model_id: str) -> bool:  # noqa: ARG002
        return True


def _make_session(monkeypatch):
    monkeypatch.setattr(InteractiveSession, "_setup_signal_handler", lambda self: None)
    return InteractiveSession(_FakeAgent())


def _status(*, exists: bool, has_access_token: bool) -> ChatGPTAuthStatus:
    return ChatGPTAuthStatus(
        provider="chatgpt",
        auth_file="/tmp/auth.json",
        exists=exists,
        has_access_token=has_access_token,
        account_id=None,
        expires_at=None,
        expired=None,
    )


async def test_pick_auth_provider_logout_no_logged_in(monkeypatch):
    session = _make_session(monkeypatch)
    infos = []

    async def fake_statuses():
        return {"chatgpt": _status(exists=False, has_access_token=False)}

    monkeypatch.setattr(interactive, "get_all_auth_provider_statuses", fake_statuses)
    monkeypatch.setattr(interactive.terminal_ui, "print_info", lambda msg: infos.append(msg))

    provider = await session._pick_auth_provider(mode="logout")

    assert provider is None
    assert infos == ["No OAuth providers logged in. Use /login first."]


async def test_handle_login_usage_error(monkeypatch):
    session = _make_session(monkeypatch)
    errors = []
    monkeypatch.setattr(
        interactive.terminal_ui,
        "print_error",
        lambda msg, title="Error": errors.append((title, msg)),
    )

    await session._handle_login_command(["/login", "extra"])

    assert errors
    assert errors[0][1] == "Usage: /login"


async def test_handle_logout_usage_error(monkeypatch):
    session = _make_session(monkeypatch)
    errors = []
    monkeypatch.setattr(
        interactive.terminal_ui,
        "print_error",
        lambda msg, title="Error": errors.append((title, msg)),
    )

    await session._handle_logout_command(["/logout", "extra"])

    assert errors
    assert errors[0][1] == "Usage: /logout"


async def test_handle_login_command_failure(monkeypatch):
    session = _make_session(monkeypatch)
    errors = []

    async def fake_pick(mode: str):
        assert mode == "login"
        return "chatgpt"

    async def fake_login(provider: str):
        assert provider == "chatgpt"
        raise RuntimeError("login failed")

    monkeypatch.setattr(session, "_pick_auth_provider", fake_pick)
    monkeypatch.setattr(interactive, "login_auth_provider", fake_login)
    monkeypatch.setattr(
        interactive.terminal_ui,
        "print_error",
        lambda msg, title="Error": errors.append((title, msg)),
    )

    await session._handle_login_command(["/login"])

    assert errors
    assert errors[0][0] == "Login Error"
    assert "login failed" in errors[0][1]


async def test_handle_login_command_cancelled(monkeypatch):
    session = _make_session(monkeypatch)
    warnings = []
    started = asyncio.Event()

    async def fake_pick(mode: str):
        assert mode == "login"
        return "chatgpt"

    async def fake_login(provider: str):
        assert provider == "chatgpt"
        started.set()
        await asyncio.sleep(60)
        return _status(exists=True, has_access_token=True)

    monkeypatch.setattr(session, "_pick_auth_provider", fake_pick)
    monkeypatch.setattr(interactive, "login_auth_provider", fake_login)
    monkeypatch.setattr(interactive.terminal_ui, "print_warning", lambda msg: warnings.append(msg))

    task = asyncio.create_task(session._handle_login_command(["/login"]))
    await started.wait()

    assert session.current_task is not None
    session.current_task.cancel()
    await task

    assert warnings == ["Login cancelled."]
    assert session.current_task is None


async def test_handle_login_syncs_models(monkeypatch):
    session = _make_session(monkeypatch)
    infos = []
    console = _DummyConsole()

    async def fake_pick(mode: str):
        assert mode == "login"
        return "chatgpt"

    async def fake_login(provider: str):
        assert provider == "chatgpt"
        return ChatGPTAuthStatus(
            provider="chatgpt",
            auth_file="/tmp/auth.json",
            exists=True,
            has_access_token=True,
            account_id="acct_123",
            expires_at=None,
            expired=None,
        )

    monkeypatch.setattr(session, "_pick_auth_provider", fake_pick)
    monkeypatch.setattr(interactive, "login_auth_provider", fake_login)
    monkeypatch.setattr(
        interactive, "sync_oauth_models", lambda mm, provider: ["chatgpt/gpt-5.2-codex"]
    )  # noqa: ARG005
    monkeypatch.setattr(interactive.terminal_ui, "print_info", lambda msg: infos.append(msg))
    monkeypatch.setattr(interactive.terminal_ui, "console", console)

    await session._handle_login_command(["/login"])

    assert any("Added 1 chatgpt models" in line for line in console.lines)
    assert infos and infos[-1] == "Run /model to pick the active model."
