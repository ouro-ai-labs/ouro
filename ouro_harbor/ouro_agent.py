"""Harbor agent implementation for ouro."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from harbor.agents.installed.base import BaseInstalledAgent, ExecInput
from harbor.models.agent.context import AgentContext


def _build_models_yaml(model_name: str, api_key: str, api_base: str | None) -> str:
    """Return the content of ``~/.ouro/models.yaml`` for the container.

    The key under ``models`` is the LiteLLM model ID (e.g.
    ``anthropic/claude-sonnet-4-5-20250929``).  ``default`` must reference
    the same key so that ``ouro --model <key>`` resolves correctly.
    """
    timeout = os.environ.get("OURO_TIMEOUT", "600")
    lines = [
        f"default: {model_name}",
        "models:",
        f"  {model_name}:",
        f"    api_key: {api_key}",
        f"    timeout: {timeout}",
    ]
    if api_base:
        lines.append(f"    api_base: {api_base}")
    return "\n".join(lines) + "\n"


class OuroAgent(BaseInstalledAgent):
    """Harbor integration for the ouro AI agent."""

    @staticmethod
    def name() -> str:
        return "ouro"

    @property
    def _install_agent_template_path(self) -> Path:
        return Path(__file__).parent / "install-ouro.sh.j2"

    def create_run_agent_commands(self, instruction: str) -> list[ExecInput]:
        model_name: str = self.model_name or "anthropic/claude-sonnet-4-5-20250929"
        api_key = os.environ.get("OURO_API_KEY", "")
        api_base = os.environ.get("OURO_BASE_URL") or None

        models_yaml = _build_models_yaml(model_name, api_key, api_base)
        escaped_yaml = shlex.quote(models_yaml)
        escaped_instruction = shlex.quote(instruction)

        env: dict[str, str] = {}
        if api_key:
            env["OURO_API_KEY"] = api_key
        if api_base:
            env["OURO_BASE_URL"] = api_base

        # Clear proxy vars that may leak from host into the container
        _PROXY_VARS = "http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy"
        unset_proxy = f"unset {_PROXY_VARS} 2>/dev/null || true"

        # Setup: write models.yaml so ouro can discover the model
        setup_command = (
            f"{unset_proxy} && "
            "mkdir -p ~/.ouro && "
            f"echo {escaped_yaml} > ~/.ouro/models.yaml && "
            "mkdir -p /logs/agent"
        )

        # Run ouro in single-task mode and tee output for log collection
        escaped_model = shlex.quote(model_name)
        run_command = (
            f"{unset_proxy} && "
            f"ouro --model {escaped_model} --task {escaped_instruction} "
            f"2>&1 | tee /logs/agent/ouro-output.txt; "
            # Copy session files to logs dir for debugging (best-effort)
            "cp -r ~/.ouro/sessions /logs/agent/sessions 2>/dev/null || true"
        )

        return [
            ExecInput(command=setup_command, env=env),
            ExecInput(command=run_command, env=env),
        ]

    def populate_context_post_run(self, context: AgentContext) -> None:
        output_path = self.logs_dir / "agent" / "ouro-output.txt"
        stdout = ""
        if output_path.exists():
            try:
                stdout = output_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                print(f"Failed to read ouro output: {exc}")

        context.metadata = {"stdout": stdout}
