"""Tests for agent/profile.py — agent profile loading, validation, and tool filtering."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agent.profile import (
    AgentProfile,
    Limits,
    ProfileValidationError,
    ToolPolicy,
    _merge_profiles,
    filter_tools,
    load_merged_profile,
    load_profile,
    validate_tool_names,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeTool:
    """Minimal stand-in for BaseTool."""

    def __init__(self, name: str, readonly: bool = False):
        self.name = name
        self.readonly = readonly


def _write_yaml(tmp: Path, data: dict | None) -> Path:
    path = tmp / "agent.yaml"
    with open(path, "w") as f:
        yaml.safe_dump(data, f)
    return path


# ---------------------------------------------------------------------------
# load_profile — basic parsing
# ---------------------------------------------------------------------------

class TestLoadProfile:
    def test_minimal(self, tmp_path):
        path = _write_yaml(tmp_path, {"name": "test"})
        p = load_profile(path)
        assert p.name == "test"
        assert p.model is None
        assert p.mode is None
        assert p.tools.allow is None
        assert p.tools.deny is None

    def test_full(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "name": "reviewer",
            "model": "openai/gpt-4o",
            "system_prompt": "You are a code reviewer.",
            "tools": {"allow": ["read_file", "grep_content"]},
            "mode": "readonly",
            "limits": {"max_iterations": 50, "max_cost_usd": 1.0},
            "reasoning_effort": "medium",
        })
        p = load_profile(path)
        assert p.name == "reviewer"
        assert p.model == "openai/gpt-4o"
        assert p.system_prompt == "You are a code reviewer."
        assert p.tools.allow == ["read_file", "grep_content"]
        assert p.tools.deny is None
        assert p.mode == "readonly"
        assert p.limits.max_iterations == 50
        assert p.limits.max_cost_usd == 1.0
        assert p.reasoning_effort == "medium"

    def test_empty_file(self, tmp_path):
        path = tmp_path / "agent.yaml"
        path.write_text("")
        p = load_profile(path)
        assert p.name is None

    def test_deny_mode(self, tmp_path):
        path = _write_yaml(tmp_path, {"tools": {"deny": ["shell", "write_file"]}})
        p = load_profile(path)
        assert p.tools.deny == ["shell", "write_file"]
        assert p.tools.allow is None


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

class TestValidation:
    def test_allow_and_deny_mutually_exclusive(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "tools": {"allow": ["read_file"], "deny": ["shell"]},
        })
        with pytest.raises(ProfileValidationError, match="mutually exclusive"):
            load_profile(path)

    def test_invalid_mode(self, tmp_path):
        path = _write_yaml(tmp_path, {"mode": "turbo"})
        with pytest.raises(ProfileValidationError, match="must be one of"):
            load_profile(path)

    def test_tools_not_a_dict(self, tmp_path):
        path = _write_yaml(tmp_path, {"tools": "read_file"})
        with pytest.raises(ProfileValidationError, match="must be a mapping"):
            load_profile(path)

    def test_allow_not_a_list(self, tmp_path):
        path = _write_yaml(tmp_path, {"tools": {"allow": "read_file"}})
        with pytest.raises(ProfileValidationError, match="must be a list"):
            load_profile(path)

    def test_limits_bad_max_iterations(self, tmp_path):
        path = _write_yaml(tmp_path, {"limits": {"max_iterations": "abc"}})
        with pytest.raises(ProfileValidationError, match="must be an integer"):
            load_profile(path)

    def test_not_a_mapping(self, tmp_path):
        path = tmp_path / "agent.yaml"
        path.write_text("- item1\n- item2\n")
        with pytest.raises(ProfileValidationError, match="must be a YAML mapping"):
            load_profile(path)

    def test_invalid_reasoning_effort(self, tmp_path):
        path = _write_yaml(tmp_path, {"reasoning_effort": "turbo"})
        with pytest.raises(ProfileValidationError, match="reasoning_effort"):
            load_profile(path)

    def test_valid_reasoning_effort(self, tmp_path):
        path = _write_yaml(tmp_path, {"reasoning_effort": "medium"})
        p = load_profile(path)
        assert p.reasoning_effort == "medium"


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

class TestMerge:
    def test_override_wins(self):
        base = AgentProfile(name="base", model="m1", reasoning_effort="low")
        override = AgentProfile(name="override", model="m2")
        merged = _merge_profiles(base, override)
        assert merged.name == "override"
        assert merged.model == "m2"
        # reasoning_effort not set in override → base value preserved
        assert merged.reasoning_effort == "low"

    def test_tools_override(self):
        base = AgentProfile(tools=ToolPolicy(deny=["shell"]))
        override = AgentProfile(tools=ToolPolicy(allow=["read_file"]))
        merged = _merge_profiles(base, override)
        assert merged.tools.allow == ["read_file"]
        assert merged.tools.deny is None

    def test_limits_partial_override(self):
        base = AgentProfile(limits=Limits(max_iterations=100, max_cost_usd=5.0))
        override = AgentProfile(limits=Limits(max_iterations=50))
        merged = _merge_profiles(base, override)
        assert merged.limits.max_iterations == 50
        assert merged.limits.max_cost_usd == 5.0


# ---------------------------------------------------------------------------
# Tool name validation
# ---------------------------------------------------------------------------

class TestToolNameValidation:
    def test_allow_unknown_is_fatal(self):
        policy = ToolPolicy(allow=["read_file", "nonexistent_tool"])
        with pytest.raises(ProfileValidationError, match="unknown tools"):
            validate_tool_names(policy, {"read_file", "write_file", "shell"})

    def test_deny_unknown_is_warning(self):
        policy = ToolPolicy(deny=["nonexistent_tool"])
        # Should not raise
        validate_tool_names(policy, {"read_file", "write_file"})


# ---------------------------------------------------------------------------
# filter_tools
# ---------------------------------------------------------------------------

class TestFilterTools:
    def _make_tools(self):
        return [
            FakeTool("read_file", readonly=True),
            FakeTool("write_file"),
            FakeTool("shell"),
            FakeTool("grep_content", readonly=True),
            FakeTool("smart_edit"),
        ]

    def test_no_policy(self):
        tools = self._make_tools()
        profile = AgentProfile()
        result = filter_tools(tools, profile)
        assert len(result) == 5

    def test_allow_filter(self):
        tools = self._make_tools()
        profile = AgentProfile(tools=ToolPolicy(allow=["read_file", "grep_content"]))
        result = filter_tools(tools, profile)
        assert {t.name for t in result} == {"read_file", "grep_content"}

    def test_deny_filter(self):
        tools = self._make_tools()
        profile = AgentProfile(tools=ToolPolicy(deny=["shell"]))
        result = filter_tools(tools, profile)
        names = {t.name for t in result}
        assert "shell" not in names
        assert len(result) == 4

    def test_readonly_mode(self):
        tools = self._make_tools()
        profile = AgentProfile(mode="readonly")
        result = filter_tools(tools, profile)
        names = {t.name for t in result}
        assert "write_file" not in names
        assert "shell" not in names
        assert "smart_edit" not in names
        assert "read_file" in names
        assert "grep_content" in names

    def test_allow_plus_readonly(self):
        tools = self._make_tools()
        # Allow includes write_file, but readonly should still remove it
        profile = AgentProfile(
            tools=ToolPolicy(allow=["read_file", "write_file"]),
            mode="readonly",
        )
        result = filter_tools(tools, profile)
        assert {t.name for t in result} == {"read_file"}


# ---------------------------------------------------------------------------
# load_merged_profile
# ---------------------------------------------------------------------------

class TestLoadMergedProfile:
    def test_no_files_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent.profile._GLOBAL_PROFILE_PATH", tmp_path / "nope.yaml")
        monkeypatch.chdir(tmp_path)
        result = load_merged_profile()
        assert result is None

    def test_cli_path_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent.profile._GLOBAL_PROFILE_PATH", tmp_path / "nope.yaml")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError):
            load_merged_profile(cli_agent_path="/nonexistent/agent.yaml")

    def test_global_only(self, tmp_path, monkeypatch):
        global_path = _write_yaml(tmp_path, {"name": "global", "model": "m1"})
        monkeypatch.setattr("agent.profile._GLOBAL_PROFILE_PATH", global_path)
        monkeypatch.chdir(tmp_path)
        result = load_merged_profile()
        assert result is not None
        assert result.name == "global"
        assert result.model == "m1"

    def test_cli_overrides_global(self, tmp_path, monkeypatch):
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        global_path = _write_yaml(global_dir, {"name": "global", "model": "m1"})

        cli_dir = tmp_path / "cli"
        cli_dir.mkdir()
        cli_path = _write_yaml(cli_dir, {"name": "cli", "model": "m2"})

        monkeypatch.setattr("agent.profile._GLOBAL_PROFILE_PATH", global_path)
        monkeypatch.chdir(tmp_path)
        result = load_merged_profile(cli_agent_path=str(cli_path))
        assert result.name == "cli"
        assert result.model == "m2"
