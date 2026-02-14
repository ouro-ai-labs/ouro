import sys
from types import SimpleNamespace

import main as ouro_main


class _DummyConsole:
    def __init__(self):
        self.lines: list[str] = []

    def print(self, *args, **kwargs):  # noqa: ARG002
        self.lines.append(" ".join(str(a) for a in args))


def _setup_common(monkeypatch, argv: list[str]):
    calls = {"error": [], "info": [], "success": [], "warning": []}
    console = _DummyConsole()

    monkeypatch.setattr(sys, "argv", ["ouro", *argv])
    monkeypatch.setattr(ouro_main, "ensure_runtime_dirs", lambda create_logs=False: None)
    monkeypatch.setattr(ouro_main, "setup_logger", lambda: None)

    monkeypatch.setattr(
        ouro_main.terminal_ui,
        "print_error",
        lambda msg, title="Error": calls["error"].append((title, msg)),
    )
    monkeypatch.setattr(
        ouro_main.terminal_ui,
        "print_info",
        lambda msg: calls["info"].append(msg),
    )
    monkeypatch.setattr(
        ouro_main.terminal_ui,
        "print_success",
        lambda msg: calls["success"].append(msg),
    )
    monkeypatch.setattr(
        ouro_main.terminal_ui,
        "print_warning",
        lambda msg: calls["warning"].append(msg),
    )
    monkeypatch.setattr(ouro_main.terminal_ui, "console", console)

    return calls, console


def test_main_rejects_login_and_logout_together(monkeypatch):
    calls, _ = _setup_common(monkeypatch, ["--login", "--logout"])

    ouro_main.main()

    assert calls["error"]
    assert calls["error"][0][0] == "Invalid Arguments"


def test_main_login_cancelled(monkeypatch):
    calls, _ = _setup_common(monkeypatch, ["--login"])

    async def fake_pick(mode: str):
        assert mode == "login"
        return None

    monkeypatch.setattr(ouro_main, "_pick_auth_provider_cli", fake_pick)

    ouro_main.main()

    assert calls["error"] == []
    assert calls["success"] == []


def test_main_login_success(monkeypatch):
    calls, console = _setup_common(monkeypatch, ["--login"])
    state = {"called": 0}

    monkeypatch.setattr(
        ouro_main,
        "ModelManager",
        lambda: SimpleNamespace(config_path="/tmp/models.yaml"),
    )
    monkeypatch.setattr(
        ouro_main,
        "sync_oauth_models",
        lambda model_manager, provider: ["chatgpt/gpt-5.2-codex"],
    )

    async def fake_pick(mode: str):
        assert mode == "login"
        return "chatgpt"

    async def fake_login(provider: str):
        state["called"] += 1
        assert provider == "chatgpt"
        return SimpleNamespace(auth_file="/tmp/auth.json", account_id="acct_123")

    monkeypatch.setattr(ouro_main, "_pick_auth_provider_cli", fake_pick)
    monkeypatch.setattr(ouro_main, "login_auth_provider", fake_login)

    ouro_main.main()

    assert state["called"] == 1
    assert calls["success"] == ["chatgpt login completed."]
    assert any("/tmp/auth.json" in line for line in console.lines)
    assert any("acct_123" in line for line in console.lines)


def test_main_login_failure(monkeypatch):
    calls, _ = _setup_common(monkeypatch, ["--login"])

    async def fake_pick(mode: str):
        assert mode == "login"
        return "chatgpt"

    async def fake_login(provider: str):
        assert provider == "chatgpt"
        raise RuntimeError("boom")

    monkeypatch.setattr(ouro_main, "_pick_auth_provider_cli", fake_pick)
    monkeypatch.setattr(ouro_main, "login_auth_provider", fake_login)

    ouro_main.main()

    assert calls["error"]
    assert calls["error"][0][0] == "Login Error"
    assert "boom" in calls["error"][0][1]


def test_main_login_cancelled_by_keyboard_interrupt(monkeypatch):
    calls, _ = _setup_common(monkeypatch, ["--login"])

    async def fake_pick(mode: str):
        assert mode == "login"
        return "chatgpt"

    async def fake_login(provider: str):
        assert provider == "chatgpt"
        raise KeyboardInterrupt

    monkeypatch.setattr(ouro_main, "_pick_auth_provider_cli", fake_pick)
    monkeypatch.setattr(ouro_main, "login_auth_provider", fake_login)

    ouro_main.main()

    assert calls["warning"] == ["Login cancelled by user."]


def test_main_logout_success(monkeypatch):
    calls, _ = _setup_common(monkeypatch, ["--logout"])

    monkeypatch.setattr(
        ouro_main,
        "ModelManager",
        lambda: SimpleNamespace(config_path="/tmp/models.yaml"),
    )
    monkeypatch.setattr(
        ouro_main,
        "remove_oauth_models",
        lambda model_manager, provider: ["chatgpt/gpt-5.2-codex"],
    )

    async def fake_pick(mode: str):
        assert mode == "logout"
        return "chatgpt"

    async def fake_logout(provider: str):
        assert provider == "chatgpt"
        return True

    monkeypatch.setattr(ouro_main, "_pick_auth_provider_cli", fake_pick)
    monkeypatch.setattr(ouro_main, "logout_auth_provider", fake_logout)

    ouro_main.main()

    assert calls["success"] == ["Logged out from chatgpt."]


def test_main_logout_cancelled_by_keyboard_interrupt(monkeypatch):
    calls, _ = _setup_common(monkeypatch, ["--logout"])

    async def fake_pick(mode: str):
        assert mode == "logout"
        return "chatgpt"

    async def fake_logout(provider: str):
        assert provider == "chatgpt"
        raise KeyboardInterrupt

    monkeypatch.setattr(ouro_main, "_pick_auth_provider_cli", fake_pick)
    monkeypatch.setattr(ouro_main, "logout_auth_provider", fake_logout)

    ouro_main.main()

    assert calls["warning"] == ["Logout cancelled by user."]


def test_main_logout_when_no_state(monkeypatch):
    calls, _ = _setup_common(monkeypatch, ["--logout"])

    monkeypatch.setattr(
        ouro_main,
        "ModelManager",
        lambda: SimpleNamespace(config_path="/tmp/models.yaml"),
    )
    monkeypatch.setattr(
        ouro_main,
        "remove_oauth_models",
        lambda model_manager, provider: [],
    )

    async def fake_pick(mode: str):
        assert mode == "logout"
        return "chatgpt"

    async def fake_logout(provider: str):
        assert provider == "chatgpt"
        return False

    monkeypatch.setattr(ouro_main, "_pick_auth_provider_cli", fake_pick)
    monkeypatch.setattr(ouro_main, "logout_auth_provider", fake_logout)

    ouro_main.main()

    assert calls["info"]
    assert calls["info"][0] == "No chatgpt login state found."


async def test_pick_auth_provider_cli_filters_for_logout(monkeypatch):
    state = {"providers": None}

    async def fake_statuses():
        return {
            "chatgpt": SimpleNamespace(
                exists=True,
                has_access_token=True,
            )
        }

    async def fake_picker(providers, title, hint):  # noqa: ARG001
        state["providers"] = providers
        return "chatgpt"

    monkeypatch.setattr(ouro_main, "get_all_auth_provider_statuses", fake_statuses)
    monkeypatch.setattr(ouro_main, "pick_oauth_provider", fake_picker)

    provider = await ouro_main._pick_auth_provider_cli(mode="logout")

    assert provider == "chatgpt"
    assert state["providers"] == [("chatgpt", "logged in")]
