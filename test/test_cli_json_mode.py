from __future__ import annotations

import sys
from types import SimpleNamespace

import ouro.interfaces.cli.main as ouro_main


class _DummyStdout:
    def __init__(self) -> None:
        self.data: list[str] = []

    def write(self, s: str) -> int:
        self.data.append(s)
        return len(s)

    def flush(self) -> None:
        return None


def test_main_passes_json_progress_sink_to_create_agent(monkeypatch):
    stdout = _DummyStdout()
    monkeypatch.setattr(sys, "argv", ["ouro-cli", "--task", "hello", "--json"])
    monkeypatch.setattr(ouro_main, "ensure_runtime_dirs", lambda create_logs=False: None)
    monkeypatch.setattr(ouro_main, "setup_logger", lambda: None)
    monkeypatch.setattr(ouro_main.Config, "validate", staticmethod(lambda: None))
    monkeypatch.setattr(sys, "stdout", stdout)

    captured: dict[str, object] = {}

    agent = SimpleNamespace(
        session_id="123",
        skills_registry=None,
        llm=object(),
        _core=SimpleNamespace(add_hook=lambda hook: None),
        set_reasoning_effort=lambda effort: None,
        run=None,
    )

    async def fake_load():
        return None

    async def fake_run(task: str, verify: bool = False):
        assert task == "hello"
        assert verify is False
        return "done"

    agent.run = fake_run

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return agent

    monkeypatch.setattr(ouro_main, "create_agent", fake_create_agent)
    monkeypatch.setattr(ouro_main, "SkillsRegistry", lambda: SimpleNamespace(load=fake_load))

    printed: list[str] = []
    monkeypatch.setattr(
        "builtins.print", lambda *args, **kwargs: printed.append(" ".join(str(a) for a in args))
    )

    ouro_main.main()

    assert captured["progress_format"] == "json"
    assert captured["progress_stream"] is stdout
    assert printed == ["done"]
