from ouro.capabilities.tools.builtins.advanced_file_ops import GlobTool, GrepTool
from ouro.capabilities.tools.builtins.file_ops import FileReadTool, FileWriteTool
from ouro.capabilities.tools.builtins.sandbox import create_sandbox_tools
from ouro.capabilities.tools.builtins.shell import ShellTool
from ouro.capabilities.tools.builtins.smart_edit import SmartEditTool
from ouro.core.sandbox import SandboxCapabilities, SandboxExecResult
from ouro.interfaces.cli.factory import _base_tools


class FakeSandboxSession:
    id = "fake"
    provider = "fake"
    capabilities = SandboxCapabilities()

    async def start(self):
        pass

    async def exec(self, command, *, cwd=None, env=None, timeout=None):
        return SandboxExecResult(stdout="", stderr="", exit_code=0)

    async def read_file(self, path, *, offset=0, limit=None):
        return ""

    async def write_file(self, path, content):
        pass

    async def glob(self, pattern, *, path="."):
        return []

    async def grep(self, pattern, **kwargs):
        return ""

    async def close(self):
        pass


def test_sandbox_enabled_base_hides_host_filesystem_and_command_tools():
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


def test_sandbox_tools_use_original_tool_names_and_native_subclasses():
    tools = create_sandbox_tools(FakeSandboxSession())
    by_name = {tool.name: tool for tool in tools}

    assert set(by_name) == {
        "shell",
        "read_file",
        "write_file",
        "smart_edit",
        "glob_files",
        "grep_content",
    }
    assert isinstance(by_name["shell"], ShellTool)
    assert isinstance(by_name["read_file"], FileReadTool)
    assert isinstance(by_name["write_file"], FileWriteTool)
    assert isinstance(by_name["smart_edit"], SmartEditTool)
    assert isinstance(by_name["glob_files"], GlobTool)
    assert isinstance(by_name["grep_content"], GrepTool)


def test_sandbox_disabled_keeps_host_filesystem_and_command_tools():
    names = {tool.name for tool in _base_tools(sandbox_enabled=False, memory_dir=None)}

    assert "shell" in names
    assert "read_file" in names
    assert "write_file" in names
    assert "smart_edit" in names
    assert "glob_files" in names
    assert "grep_content" in names
