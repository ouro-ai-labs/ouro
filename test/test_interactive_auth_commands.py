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
        self.model_manager = object()
        self.memory = SimpleNamespace(get_stats=lambda: {})


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


async def test_handle_auth_status_usage_error(monkeypatch):
    session = _make_session(monkeypatch)
    errors = []
    monkeypatch.setattr(
        interactive.terminal_ui,
        "print_error",
        lambda msg, title="Error": errors.append((title, msg)),
    )

    await session._handle_auth_status_command(["/auth", "extra"])

    assert errors
    assert errors[0][1] == "Usage: /auth"


async def test_handle_auth_status_not_logged_in(monkeypatch):
    session = _make_session(monkeypatch)
    console = _DummyConsole()
    monkeypatch.setattr(interactive.terminal_ui, "console", console)

    async def fake_statuses():
        return {"chatgpt": _status(exists=False, has_access_token=False)}

    monkeypatch.setattr(interactive, "get_all_auth_provider_statuses", fake_statuses)

    await session._handle_auth_status_command(["/auth"])

    assert any("OAuth Auth Status" in line for line in console.lines)
    assert any("not logged in" in line for line in console.lines)


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
