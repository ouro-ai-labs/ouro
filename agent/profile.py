"""Agent profile configuration — defines agent behavior via YAML config files.

Supports a two-tier config system:
  1. System-wide:  ~/.ouro/agent.yaml  (user defaults)
  2. Project-local: .agent-profile.yaml (project overrides)
  3. CLI explicit:  --agent <path>      (highest priority)

Merge order: system defaults < project config < CLI explicit.
CLI flags (--model, --reasoning-effort) always win over profile values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from llm.reasoning import REASONING_EFFORT_CHOICES, normalize_reasoning_effort
from utils import get_logger

logger = get_logger(__name__)

# Well-known file locations
_GLOBAL_PROFILE_PATH = Path.home() / ".ouro" / "agent.yaml"
_PROJECT_PROFILE_NAME = ".agent-profile.yaml"


class ProfileValidationError(Exception):
    """Raised when an agent profile fails validation."""


@dataclass
class ToolPolicy:
    """Tool allow/deny policy.

    Exactly one of ``allow`` or ``deny`` may be set (mutually exclusive).
    When ``allow`` is set, only listed tools are available (whitelist).
    When ``deny`` is set, all tools *except* listed ones are available (blacklist).
    """

    allow: list[str] | None = None
    deny: list[str] | None = None


@dataclass
class Limits:
    """Resource limits for an agent run."""

    max_iterations: int | None = None
    max_cost_usd: float | None = None  # reserved — warn only, no hard-stop in MVP


@dataclass
class AgentProfile:
    """A single agent profile loaded from YAML."""

    name: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    tools: ToolPolicy = field(default_factory=ToolPolicy)
    mode: str | None = None  # "readonly" | "full" | None (default = full)
    limits: Limits = field(default_factory=Limits)
    reasoning_effort: str | None = None

    # Source path (for diagnostics)
    _source: str | None = field(default=None, repr=False)


def _parse_tool_policy(raw: Any) -> ToolPolicy:
    """Parse the ``tools`` section from raw YAML dict."""
    if raw is None:
        return ToolPolicy()
    if not isinstance(raw, dict):
        raise ProfileValidationError(
            f"'tools' must be a mapping with 'allow' or 'deny', got {type(raw).__name__}"
        )
    allow = raw.get("allow")
    deny = raw.get("deny")
    if allow is not None and deny is not None:
        raise ProfileValidationError(
            "'tools.allow' and 'tools.deny' are mutually exclusive — use one or the other"
        )
    if allow is not None and not isinstance(allow, list):
        raise ProfileValidationError("'tools.allow' must be a list of tool names")
    if deny is not None and not isinstance(deny, list):
        raise ProfileValidationError("'tools.deny' must be a list of tool names")
    return ToolPolicy(allow=allow, deny=deny)


def _parse_limits(raw: Any) -> Limits:
    """Parse the ``limits`` section from raw YAML dict."""
    if raw is None:
        return Limits()
    if not isinstance(raw, dict):
        raise ProfileValidationError(f"'limits' must be a mapping, got {type(raw).__name__}")
    max_iter = raw.get("max_iterations")
    max_cost = raw.get("max_cost_usd")
    if max_iter is not None:
        try:
            max_iter = int(max_iter)
        except (TypeError, ValueError) as exc:
            raise ProfileValidationError(
                f"'limits.max_iterations' must be an integer, got {max_iter!r}"
            ) from exc
    if max_cost is not None:
        try:
            max_cost = float(max_cost)
        except (TypeError, ValueError) as exc:
            raise ProfileValidationError(
                f"'limits.max_cost_usd' must be a number, got {max_cost!r}"
            ) from exc
        logger.warning(
            "limits.max_cost_usd is reserved — will log warnings but not enforce a hard budget stop"
        )
    return Limits(max_iterations=max_iter, max_cost_usd=max_cost)


_KNOWN_KEYS = {"name", "model", "system_prompt", "tools", "mode", "limits", "reasoning_effort"}
_VALID_MODES = {"readonly", "full"}


def load_profile(path: str | Path) -> AgentProfile:
    """Load and validate a single agent profile from a YAML file.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed ``AgentProfile``.

    Raises:
        ProfileValidationError: On schema or semantic errors.
        FileNotFoundError: If the file does not exist.
    """
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        # Empty file — treat as empty profile
        return AgentProfile(_source=str(path))

    if not isinstance(raw, dict):
        raise ProfileValidationError(f"Profile must be a YAML mapping, got {type(raw).__name__}")

    # Warn on unknown keys (forward-compat)
    unknown = set(raw.keys()) - _KNOWN_KEYS
    if unknown:
        logger.warning("Unknown keys in %s (ignored): %s", path, ", ".join(sorted(unknown)))

    # Parse mode
    mode = raw.get("mode")
    if mode is not None:
        mode = str(mode).lower()
        if mode not in _VALID_MODES:
            raise ProfileValidationError(f"'mode' must be one of {_VALID_MODES}, got {mode!r}")

    # Validate reasoning_effort early (before it hits set_reasoning_effort)
    reasoning_effort = raw.get("reasoning_effort")
    if reasoning_effort is not None:
        try:
            normalize_reasoning_effort(str(reasoning_effort))
        except ValueError as exc:
            allowed = ", ".join(REASONING_EFFORT_CHOICES)
            raise ProfileValidationError(
                f"'reasoning_effort' must be one of [{allowed}], got {reasoning_effort!r}"
            ) from exc

    return AgentProfile(
        name=raw.get("name"),
        model=raw.get("model"),
        system_prompt=raw.get("system_prompt"),
        tools=_parse_tool_policy(raw.get("tools")),
        mode=mode,
        limits=_parse_limits(raw.get("limits")),
        reasoning_effort=reasoning_effort,
        _source=str(path),
    )


def _merge_profiles(base: AgentProfile, override: AgentProfile) -> AgentProfile:
    """Merge two profiles — *override* wins for any non-None field."""
    return AgentProfile(
        name=override.name if override.name is not None else base.name,
        model=override.model if override.model is not None else base.model,
        system_prompt=(
            override.system_prompt if override.system_prompt is not None else base.system_prompt
        ),
        tools=(
            override.tools
            if (override.tools.allow is not None or override.tools.deny is not None)
            else base.tools
        ),
        mode=override.mode if override.mode is not None else base.mode,
        limits=Limits(
            max_iterations=(
                override.limits.max_iterations
                if override.limits.max_iterations is not None
                else base.limits.max_iterations
            ),
            max_cost_usd=(
                override.limits.max_cost_usd
                if override.limits.max_cost_usd is not None
                else base.limits.max_cost_usd
            ),
        ),
        reasoning_effort=(
            override.reasoning_effort
            if override.reasoning_effort is not None
            else base.reasoning_effort
        ),
        _source=override._source or base._source,
    )


def _find_project_profile() -> Path | None:
    """Walk from cwd upward looking for .agent-profile.yaml."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / _PROJECT_PROFILE_NAME
        if candidate.is_file():
            return candidate
    return None


def load_merged_profile(cli_agent_path: str | None = None) -> AgentProfile | None:
    """Load the effective agent profile by merging all tiers.

    Priority (highest wins): CLI --agent > project .agent-profile.yaml > ~/.ouro/agent.yaml.

    Returns:
        Merged ``AgentProfile``, or ``None`` if no profile files exist
        and no ``--agent`` was provided.

    Raises:
        ProfileValidationError: On validation errors in any tier.
        FileNotFoundError: If ``--agent`` path does not exist.
    """
    layers: list[AgentProfile] = []

    # Tier 1: global
    if _GLOBAL_PROFILE_PATH.is_file():
        logger.debug("Loading global profile: %s", _GLOBAL_PROFILE_PATH)
        layers.append(load_profile(_GLOBAL_PROFILE_PATH))

    # Tier 2: project-local
    project_path = _find_project_profile()
    if project_path is not None:
        logger.debug("Loading project profile: %s", project_path)
        layers.append(load_profile(project_path))

    # Tier 3: CLI explicit
    if cli_agent_path is not None:
        path = Path(cli_agent_path)
        if not path.is_file():
            raise FileNotFoundError(f"Agent profile not found: {cli_agent_path}")
        logger.debug("Loading CLI profile: %s", path)
        layers.append(load_profile(path))

    if not layers:
        return None

    result = layers[0]
    for layer in layers[1:]:
        result = _merge_profiles(result, layer)
    return result


# ---------------------------------------------------------------------------
# Tool filtering helpers
# ---------------------------------------------------------------------------

# Tools that perform writes / mutations. Used to enforce ``mode: readonly``.
WRITE_TOOLS = frozenset({"write_file", "smart_edit", "shell"})


def validate_tool_names(policy: ToolPolicy, available: set[str]) -> None:
    """Check that tool names in the policy actually exist.

    - In ``allow`` mode: unknown names raise ``ProfileValidationError`` (fatal).
    - In ``deny`` mode: unknown names emit a warning.
    """
    if policy.allow is not None:
        unknown = set(policy.allow) - available
        if unknown:
            raise ProfileValidationError(
                f"tools.allow references unknown tools: {', '.join(sorted(unknown))}. "
                f"Available tools: {', '.join(sorted(available))}"
            )
    if policy.deny is not None:
        unknown = set(policy.deny) - available
        if unknown:
            logger.warning(
                "tools.deny references unknown tools (ignored): %s",
                ", ".join(sorted(unknown)),
            )


def filter_tools(tools: list, profile: AgentProfile) -> list:
    """Return a filtered copy of the tools list according to the profile.

    Applies both the explicit allow/deny policy and the ``mode: readonly`` rule.

    Args:
        tools: List of ``BaseTool`` instances.
        profile: The effective agent profile.

    Returns:
        Filtered list of tools.
    """
    available_names = {t.name for t in tools}

    # Validate policy names against available tools
    validate_tool_names(profile.tools, available_names)

    # Apply allow/deny
    if profile.tools.allow is not None:
        allowed = set(profile.tools.allow)
        tools = [t for t in tools if t.name in allowed]
    elif profile.tools.deny is not None:
        denied = set(profile.tools.deny)
        tools = [t for t in tools if t.name not in denied]

    # Apply readonly mode — remove write tools
    if profile.mode == "readonly":
        tools = [t for t in tools if t.name not in WRITE_TOOLS]

    return tools
