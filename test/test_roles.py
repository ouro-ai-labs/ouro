"""Tests for the role system."""

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from roles import RoleConfig, RoleManager
from roles.types import MemoryOverrides, SkillsConfig, VerificationConfig


class TestRoleConfig:
    """Test RoleConfig data model."""

    def test_defaults(self):
        role = RoleConfig(name="test", description="test role")
        assert role.name == "test"
        assert role.system_prompt is None
        assert role.tools is None
        assert role.agents_md is True
        assert role.memory == MemoryOverrides()
        assert role.skills == SkillsConfig()
        assert role.verification == VerificationConfig()
        assert role.source_path is None

    def test_frozen(self):
        role = RoleConfig(name="test", description="test")
        with pytest.raises(AttributeError):
            role.name = "other"  # type: ignore[misc]

    def test_memory_overrides_defaults(self):
        mo = MemoryOverrides()
        assert mo.short_term_size is None
        assert mo.compression_threshold is None
        assert mo.compression_ratio is None
        assert mo.strategy is None
        assert mo.long_term_memory is None

    def test_skills_config_defaults(self):
        sc = SkillsConfig()
        assert sc.enabled is True
        assert sc.allowed is None

    def test_verification_config_defaults(self):
        vc = VerificationConfig()
        assert vc.enabled is True
        assert vc.max_iterations == 3


class TestRoleManager:
    """Test RoleManager loading and lookup."""

    def test_general_always_exists(self):
        """General role must always be available even with empty directories."""
        with (
            patch("roles.manager.BUILTIN_ROLES_DIR", Path("/nonexistent")),
            patch("roles.manager.USER_ROLES_DIR", Path("/nonexistent")),
        ):
            mgr = RoleManager()
            assert "general" in mgr.roles
            role = mgr.get_role("general")
            assert role is not None
            assert role.name == "general"

    def test_loads_builtin_roles(self):
        """Builtin roles directory should be loaded."""
        mgr = RoleManager()
        assert "general" in mgr.roles
        assert "searcher" in mgr.roles
        assert "debugger" in mgr.roles
        assert "coder" in mgr.roles

    def test_list_roles(self):
        mgr = RoleManager()
        roles = mgr.list_roles()
        names = [r.name for r in roles]
        assert "general" in names
        assert "searcher" in names

    def test_get_role_names(self):
        mgr = RoleManager()
        names = mgr.get_role_names()
        assert "general" in names
        assert "searcher" in names

    def test_get_nonexistent_role(self):
        mgr = RoleManager()
        assert mgr.get_role("nonexistent_role_xyz") is None

    def test_user_yaml_overrides_builtin(self, tmp_path):
        """User roles should override builtin roles of the same name."""
        user_dir = tmp_path / "roles"
        user_dir.mkdir()
        (user_dir / "searcher.yaml").write_text(
            textwrap.dedent(
                """\
            name: searcher
            description: Custom searcher
            system_prompt: |
              Custom prompt
            """
            )
        )

        with patch("roles.manager.USER_ROLES_DIR", user_dir):
            mgr = RoleManager()
            role = mgr.get_role("searcher")
            assert role is not None
            assert role.description == "Custom searcher"
            assert "Custom prompt" in role.system_prompt

    def test_malformed_yaml_skipped(self, tmp_path):
        """Malformed YAML files should be skipped with a warning, not crash."""
        user_dir = tmp_path / "roles"
        user_dir.mkdir()
        (user_dir / "bad.yaml").write_text(":::invalid yaml{{{}}")

        with patch("roles.manager.USER_ROLES_DIR", user_dir):
            mgr = RoleManager()
            # Should still have builtin roles
            assert "general" in mgr.roles

    def test_yaml_missing_name_skipped(self, tmp_path):
        """YAML files without 'name' field should be skipped."""
        user_dir = tmp_path / "roles"
        user_dir.mkdir()
        (user_dir / "noname.yaml").write_text("description: no name field\n")

        with patch("roles.manager.USER_ROLES_DIR", user_dir):
            mgr = RoleManager()
            # Should not crash; builtin roles still there
            assert "general" in mgr.roles


class TestBuiltinRoles:
    """Test properties of built-in roles."""

    def test_searcher_role(self):
        mgr = RoleManager()
        role = mgr.get_role("searcher")
        assert role is not None
        assert role.system_prompt is not None
        assert role.tools is not None
        assert "web_search" in role.tools
        assert "web_fetch" in role.tools
        assert role.agents_md is False
        assert role.memory.long_term_memory is False
        assert role.skills.enabled is False
        assert role.verification.enabled is False

    def test_debugger_role(self):
        mgr = RoleManager()
        role = mgr.get_role("debugger")
        assert role is not None
        assert role.system_prompt is not None
        assert role.tools is not None
        assert "read_file" in role.tools
        assert "shell" in role.tools
        assert "write_file" not in role.tools
        assert "smart_edit" not in role.tools
        assert role.agents_md is True
        assert role.skills.enabled is False
        assert role.verification.enabled is False

    def test_coder_role(self):
        mgr = RoleManager()
        role = mgr.get_role("coder")
        assert role is not None
        assert role.system_prompt is not None
        assert role.tools is not None
        assert "read_file" in role.tools
        assert "write_file" in role.tools
        assert "smart_edit" in role.tools
        assert "shell" in role.tools
        assert "grep_content" in role.tools
        assert "manage_todo_list" in role.tools
        assert "web_search" not in role.tools
        assert role.agents_md is True
        assert role.skills.enabled is False
        assert role.verification.enabled is True
        assert role.verification.max_iterations == 3

    def test_general_role(self):
        mgr = RoleManager()
        role = mgr.get_role("general")
        assert role is not None
        assert role.system_prompt is None  # Uses full LoopAgent.SYSTEM_PROMPT
        assert role.tools is None  # All tools


class TestToolFiltering:
    """Test that tool whitelists work correctly."""

    def test_role_with_tool_whitelist(self):
        role = RoleConfig(
            name="limited",
            description="limited tools",
            tools=["read_file", "glob_files"],
        )
        assert role.tools is not None
        assert "read_file" in role.tools
        assert "shell" not in role.tools

    def test_todo_tool_included_when_listed(self):
        """manage_todo_list in whitelist means TodoTool should be added."""
        role = RoleConfig(
            name="with_todo",
            description="has todo",
            tools=["read_file", "manage_todo_list"],
        )
        assert "manage_todo_list" in role.tools

    def test_todo_tool_excluded_when_not_listed(self):
        """manage_todo_list not in whitelist means TodoTool excluded."""
        role = RoleConfig(
            name="no_todo",
            description="no todo",
            tools=["read_file"],
        )
        assert "manage_todo_list" not in role.tools

    def test_no_tools_means_all(self):
        """tools=None means all tools available."""
        role = RoleConfig(name="all", description="all tools")
        assert role.tools is None


class TestMemoryOverrides:
    """Test memory configuration overrides from roles."""

    def test_searcher_memory_overrides(self):
        mgr = RoleManager()
        role = mgr.get_role("searcher")
        assert role is not None
        assert role.memory.short_term_size == 50
        assert role.memory.compression_threshold == 30000
        assert role.memory.compression_ratio == 0.3
        assert role.memory.strategy == "sliding_window"
        assert role.memory.long_term_memory is False

    def test_general_no_overrides(self):
        mgr = RoleManager()
        role = mgr.get_role("general")
        assert role is not None
        # General role has no overrides (all None)
        assert role.memory.short_term_size is None
        assert role.memory.compression_threshold is None


class TestSystemPromptComposition:
    """Test system prompt building per role."""

    def test_general_uses_full_prompt(self):
        """General role (system_prompt=None) should use full SYSTEM_PROMPT."""
        from agent.agent import LoopAgent

        # We can't call _build_system_prompt without a full agent, but we can
        # verify the SYSTEM_PROMPT contains all sections
        assert "<role>" in LoopAgent.SYSTEM_PROMPT
        assert "<agents_md>" in LoopAgent.SYSTEM_PROMPT
        assert "<task_management>" in LoopAgent.SYSTEM_PROMPT
        assert "<workflow>" in LoopAgent.SYSTEM_PROMPT

    def test_prompt_sections_exist(self):
        """All named prompt sections should be accessible as class attributes."""
        from agent.agent import LoopAgent

        assert hasattr(LoopAgent, "PROMPT_ROLE")
        assert hasattr(LoopAgent, "PROMPT_CRITICAL_RULES")
        assert hasattr(LoopAgent, "PROMPT_AGENTS_MD")
        assert hasattr(LoopAgent, "PROMPT_TASK_MANAGEMENT")
        assert hasattr(LoopAgent, "PROMPT_TOOL_GUIDELINES")
        assert hasattr(LoopAgent, "PROMPT_WORKFLOW")
        assert hasattr(LoopAgent, "PROMPT_COMPLEX_STRATEGY")

    def test_system_prompt_is_join_of_sections(self):
        """SYSTEM_PROMPT should be composed from all section constants."""
        from agent.agent import LoopAgent

        assert LoopAgent.PROMPT_ROLE in LoopAgent.SYSTEM_PROMPT
        assert LoopAgent.PROMPT_AGENTS_MD in LoopAgent.SYSTEM_PROMPT
        assert LoopAgent.PROMPT_TASK_MANAGEMENT in LoopAgent.SYSTEM_PROMPT
        assert LoopAgent.PROMPT_COMPLEX_STRATEGY in LoopAgent.SYSTEM_PROMPT


class TestToolRegistry:
    """Test the tool registry module."""

    def test_create_core_tools_all(self):
        from tools.registry import create_core_tools

        tools = create_core_tools()
        names = {t.name for t in tools}
        assert "read_file" in names
        assert "shell" in names
        assert "web_search" in names

    def test_create_core_tools_filtered(self):
        from tools.registry import create_core_tools

        tools = create_core_tools(names=["read_file", "glob_files"])
        names = {t.name for t in tools}
        assert names == {"read_file", "glob_files"}

    def test_create_core_tools_unknown_ignored(self):
        from tools.registry import create_core_tools

        tools = create_core_tools(names=["read_file", "nonexistent_tool"])
        names = {t.name for t in tools}
        assert names == {"read_file"}

    def test_get_all_tool_names(self):
        from tools.registry import get_all_tool_names

        names = get_all_tool_names()
        assert "read_file" in names
        assert "explore_context" in names
        assert "parallel_execute" in names
