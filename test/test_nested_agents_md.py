"""Tests for lazy subdirectory AGENTS.md loading (NestedAgentsMdRule + helpers).

Offline, no API keys. Tests scope discovery to a tmp directory via explicit
``cwd`` / ``file_path`` arguments so results don't depend on the machine.
"""

from ouro.capabilities.context.agents_md import (
    _nested_agents_md_paths,
    load_nested_instructions,
)
from ouro.capabilities.rules.nested_agents_md import NestedAgentsMdRule
from ouro.core.llm import ToolCall, ToolResult

# --- path discovery ----------------------------------------------------------


def test_paths_walk_cwd_down_to_target(tmp_path):
    # cwd/a/b/file.txt with AGENTS.md at a/ and a/b/
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "AGENTS.md").write_text("A RULE")
    (tmp_path / "a" / "b" / "AGENTS.md").write_text("B RULE")
    target = tmp_path / "a" / "b" / "file.txt"

    paths = _nested_agents_md_paths(str(tmp_path), str(target))

    # parent-first, nearest last; only the two on the path, not cwd-level.
    assert [p.parent.name for p in paths] == ["a", "b"]


def test_paths_excludes_cwd_level_and_above(tmp_path):
    # A file directly in cwd pulls in nothing (cwd & above are eagerly loaded).
    (tmp_path / "AGENTS.md").write_text("ROOT RULE")
    target = tmp_path / "file.txt"
    assert _nested_agents_md_paths(str(tmp_path), str(target)) == []


def test_paths_ignores_files_outside_cwd(tmp_path):
    cwd = tmp_path / "proj"
    cwd.mkdir()
    outside = tmp_path / "other" / "file.txt"
    outside.parent.mkdir()
    (tmp_path / "other" / "AGENTS.md").write_text("NOPE")
    assert _nested_agents_md_paths(str(cwd), str(outside)) == []


def test_paths_skips_siblings(tmp_path):
    # Reading a/b/file.txt must not pull a/c/AGENTS.md (sibling subtree).
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "c").mkdir()
    (tmp_path / "a" / "c" / "AGENTS.md").write_text("SIBLING")
    target = tmp_path / "a" / "b" / "file.txt"
    assert _nested_agents_md_paths(str(tmp_path), str(target)) == []


# --- load + dedup ------------------------------------------------------------


def test_load_formats_block_and_dedups(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "AGENTS.md").write_text("SUBDIR RULE")
    target = tmp_path / "a" / "file.txt"
    injected: set[str] = set()

    first = load_nested_instructions(str(tmp_path), str(target), injected)
    assert "<project_instructions>" in first
    assert "SUBDIR RULE" in first

    # Second read of a file in the same subdir injects nothing (already seen).
    second = load_nested_instructions(str(tmp_path), str(target), injected)
    assert second == ""


def test_load_returns_empty_when_no_nested_agents_md(tmp_path):
    (tmp_path / "a").mkdir()
    target = tmp_path / "a" / "file.txt"
    assert load_nested_instructions(str(tmp_path), str(target), set()) == ""


# --- rule integration --------------------------------------------------------


def _ctx():
    # The rule only uses ctx for run-identity dedup; any sentinel object works.
    return object()


def test_rule_appends_nested_block_to_read_result(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "AGENTS.md").write_text("NESTED RULE")
    rule = NestedAgentsMdRule(cwd=str(tmp_path))
    call = ToolCall(id="1", name="read_file", arguments={"file_path": str(tmp_path / "a" / "x.py")})
    result = ToolResult(tool_call_id="1", content="<file contents>", name="read_file")

    out = rule.after_toolcall(_ctx(), call, result)

    assert out is not None
    assert out.startswith("<file contents>")
    assert "NESTED RULE" in out
    assert "<project_instructions>" in out


def test_rule_ignores_non_read_tools(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "AGENTS.md").write_text("NESTED RULE")
    rule = NestedAgentsMdRule(cwd=str(tmp_path))
    call = ToolCall(
        id="1", name="write_file", arguments={"file_path": str(tmp_path / "a" / "x.py")}
    )
    result = ToolResult(tool_call_id="1", content="ok", name="write_file")
    assert rule.after_toolcall(_ctx(), call, result) is None


def test_rule_dedups_within_run_but_resets_across_runs(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "AGENTS.md").write_text("NESTED RULE")
    rule = NestedAgentsMdRule(cwd=str(tmp_path))
    call = ToolCall(id="1", name="read_file", arguments={"file_path": str(tmp_path / "a" / "x.py")})
    result = ToolResult(tool_call_id="1", content="c", name="read_file")

    run1 = _ctx()
    assert rule.after_toolcall(run1, call, result) is not None  # first read in run1
    assert rule.after_toolcall(run1, call, result) is None  # deduped in run1

    run2 = _ctx()  # new run context identity → dedup set resets
    assert rule.after_toolcall(run2, call, result) is not None


def test_rule_no_nested_returns_none_unchanged(tmp_path):
    rule = NestedAgentsMdRule(cwd=str(tmp_path))
    # File directly in cwd → nothing nested.
    call = ToolCall(id="1", name="read_file", arguments={"file_path": str(tmp_path / "x.py")})
    result = ToolResult(tool_call_id="1", content="c", name="read_file")
    assert rule.after_toolcall(_ctx(), call, result) is None
