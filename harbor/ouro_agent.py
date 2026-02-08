"""Harbor agent implementation for ouro."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from harbor.agents.installed.base import BaseInstalledAgent, ExecInput
from harbor.models.agent.context import AgentContext

# Provider prefix → environment variable for the API key
_PROVIDER_KEY_MAP: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "together_ai": "TOGETHERAI_API_KEY",
    "fireworks_ai": "FIREWORKS_API_KEY",
    "cohere": "CO_API_KEY",
}


def _resolve_api_key(model_name: str | None) -> str:
    """Pick the right API key env-var value based on the model's provider prefix.

    Falls back to ``OURO_API_KEY`` if the provider-specific variable is unset.
    """
    if model_name and "/" in model_name:
        provider = model_name.split("/")[0].lower()
        env_var = _PROVIDER_KEY_MAP.get(provider)
        if env_var:
            value = os.environ.get(env_var, "")
            if value:
                return value

    # Generic fallback
    return os.environ.get("OURO_API_KEY", "")


def _build_models_yaml(model_name: str, api_key: str) -> str:
    """Return the content of ``~/.ouro/models.yaml`` for the container."""
    timeout = os.environ.get("OURO_TIMEOUT", "600")
    return (
        f"default: harbor-model\n"
        f"models:\n"
        f"  harbor-model:\n"
        f"    api_key: {api_key}\n"
        f"    timeout: {timeout}\n"
    )


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
        api_key = _resolve_api_key(model_name)

        models_yaml = _build_models_yaml(model_name, api_key)
        escaped_yaml = shlex.quote(models_yaml)
        escaped_instruction = shlex.quote(instruction)

        # Propagate provider-specific key + generic fallback into the container
        env: dict[str, str] = {}
        if model_name and "/" in model_name:
            provider = model_name.split("/")[0].lower()
            env_var = _PROVIDER_KEY_MAP.get(provider)
            if env_var:
                value = os.environ.get(env_var, "")
                if value:
                    env[env_var] = value
        ouro_key = os.environ.get("OURO_API_KEY", "")
        if ouro_key:
            env["OURO_API_KEY"] = ouro_key

        # Setup: write models.yaml so ouro can discover the model
        setup_command = (
            "mkdir -p ~/.ouro && "
            f"echo {escaped_yaml} > ~/.ouro/models.yaml && "
            "mkdir -p /logs/agent"
        )

        # Run ouro in single-task mode and tee output for log collection
        run_command = (
            f"ouro --model harbor-model --task {escaped_instruction} "
            f"2>&1 | tee /logs/agent/ouro-output.txt"
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
