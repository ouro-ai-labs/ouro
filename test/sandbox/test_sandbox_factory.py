from ouro.interfaces.cli.factory import _base_tools


def test_sandbox_enabled_hides_host_filesystem_and_command_tools():
    names = {tool.name for tool in _base_tools(sandbox_enabled=True, memory_dir=None)}

    assert "web_search" in names
    assert "web_fetch" in names
    assert "conversation_search" in names
    assert "shell" not in names
    assert "read_file" not in names
    assert "write_file" not in names
    assert "smart_edit" not in names
    assert "glob_files" not in names
    assert "grep_content" not in names


def test_sandbox_disabled_keeps_host_filesystem_and_command_tools():
    names = {tool.name for tool in _base_tools(sandbox_enabled=False, memory_dir=None)}

    assert "shell" in names
    assert "read_file" in names
    assert "write_file" in names
    assert "smart_edit" in names
    assert "glob_files" in names
    assert "grep_content" in names
