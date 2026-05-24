"""Tests for deterministic AGENTS.md auto-loading.

Offline, no API keys. Each test scopes the upward walk to a tmp directory via
the ``start_dir`` argument so results don't depend on the developer's machine.
"""

from ouro.capabilities.context.agents_md import _discover_agents_md, load_agents_md


async def test_no_agents_md_returns_empty(tmp_path):
    assert await load_agents_md(str(tmp_path)) == ""


async def test_single_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Run the tests before committing.")
    block = await load_agents_md(str(tmp_path))
    assert "<project_instructions>" in block
    assert "</project_instructions>" in block
    assert "Run the tests before committing." in block


async def test_upward_walk_merge_order_nearest_last(tmp_path):
    child = tmp_path / "sub" / "deep"
    child.mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("PARENT RULE")
    (child / "AGENTS.md").write_text("CHILD RULE")

    block = await load_agents_md(str(child))

    # Both present, and the nearest (child) appears after the parent so it
    # takes precedence in the merged prompt.
    assert "PARENT RULE" in block
    assert "CHILD RULE" in block
    assert block.index("PARENT RULE") < block.index("CHILD RULE")


async def test_empty_file_skipped(tmp_path):
    (tmp_path / "AGENTS.md").write_text("   \n\t  \n")
    assert await load_agents_md(str(tmp_path)) == ""


async def test_uses_cwd_by_default(tmp_path, monkeypatch):
    (tmp_path / "AGENTS.md").write_text("CWD RULE")
    monkeypatch.chdir(tmp_path)
    block = await load_agents_md()
    assert "CWD RULE" in block


def test_discover_orders_parent_first(tmp_path):
    child = tmp_path / "sub"
    child.mkdir()
    (tmp_path / "AGENTS.md").write_text("parent")
    (child / "AGENTS.md").write_text("child")

    found = _discover_agents_md(str(child))

    assert [p.parent for p in found] == [tmp_path.resolve(), child.resolve()]
