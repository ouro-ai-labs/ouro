"""Harbor agent implementation for ouro."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from harbor.agents.installed.base import BaseInstalledAgent, ExecInput
from harbor.models.agent.context import AgentContext

_PROXY_VARS = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "all_proxy",
)


def _rewrite_proxy_url(url: str) -> str:
    """Rewrite 127.0.0.1/localhost to host.docker.internal for Docker access."""
    return re.sub(
        r"://(127\.0\.0\.1|localhost):",
        "://host.docker.internal:",
        url,
    )


def _proxy_env() -> dict[str, str]:
    """Return proxy env vars rewritten for use inside a Docker container."""
    env: dict[str, str] = {}
    for var in _PROXY_VARS:
        val = os.environ.get(var)
        if val:
            env[var] = _rewrite_proxy_url(val)
    return env


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
    """Harbor integration for the ouro AI agent.

    Supported kwargs (passed via harbor agent config):
        git_ref: Install from a git branch/tag/commit instead of PyPI.
                 e.g. ``git_ref: "multi-role"`` installs from that branch.
        role:    Agent role to use (e.g. ``role: "coder"``).
                 Requires a version that supports ``--role``.
    """

    def __init__(self, *args, **kwargs):
        self._extra_kwargs = dict(kwargs)
        super().__init__(*args, **kwargs)

    @staticmethod
    def name() -> str:
        return "ouro"

    @property
    def _install_agent_template_path(self) -> Path:
        return Path(__file__).parent / "install-ouro.sh.j2"

    @property
    def _template_variables(self) -> dict[str, str]:
        variables = super()._template_variables
        git_ref = self._extra_kwargs.get("git_ref")
        if git_ref:
            variables["git_ref"] = git_ref
        return variables

    def create_run_agent_commands(self, instruction: str) -> list[ExecInput]:
        model_name: str = self.model_name or "anthropic/claude-sonnet-4-5-20250929"
        api_key = os.environ.get("OURO_API_KEY", "")
        api_base = os.environ.get("OURO_BASE_URL") or None

        models_yaml = _build_models_yaml(model_name, api_key, api_base)
        escaped_yaml = shlex.quote(models_yaml)
        escaped_instruction = shlex.quote(instruction)

        env: dict[str, str] = _proxy_env()
        if api_key:
            env["OURO_API_KEY"] = api_key
        if api_base:
            env["OURO_BASE_URL"] = api_base

        # Setup: write models.yaml so ouro can discover the model
        setup_command = (
            "mkdir -p ~/.ouro && "
            f"echo {escaped_yaml} > ~/.ouro/models.yaml && "
            "mkdir -p /logs/agent"
        )

        # Run ouro in single-task mode and tee output for log collection
        escaped_model = shlex.quote(model_name)
        role = self._extra_kwargs.get("role")
        role_flag = f" --role {shlex.quote(role)}" if role else ""
        run_command = (
            f"ouro --model {escaped_model}{role_flag} --task {escaped_instruction} "
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
