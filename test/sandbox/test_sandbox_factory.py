from ouro.capabilities.tools.builtins.advanced_file_ops import GlobTool, GrepTool
from ouro.capabilities.tools.builtins.file_ops import FileReadTool, FileWriteTool
from ouro.capabilities.tools.builtins.sandbox import create_default_tools
from ouro.capabilities.tools.builtins.shell import ShellTool
from ouro.capabilities.tools.builtins.smart_edit import SmartEditTool
from ouro.core.sandbox import SandboxCapabilities, SandboxExecResult


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


def test_sandbox_enabled_default_tools_use_sandbox_for_filesystem_and_command_tools():
    tools = create_default_tools(sandbox_session=FakeSandboxSession(), memory_dir=None)
    by_name = {tool.name: tool for tool in tools}

    assert set(by_name) >= {
        "shell",
        "read_file",
        "write_file",
        "smart_edit",
        "glob_files",
        "grep_content",
        "web_search",
        "web_fetch",
        "conversation_search",
    }
    assert isinstance(by_name["shell"], ShellTool)
    assert by_name["shell"].__class__ is not ShellTool
    assert isinstance(by_name["read_file"], FileReadTool)
    assert by_name["read_file"].__class__ is not FileReadTool
    assert isinstance(by_name["write_file"], FileWriteTool)
    assert by_name["write_file"].__class__ is not FileWriteTool
    assert isinstance(by_name["smart_edit"], SmartEditTool)
    assert by_name["smart_edit"].__class__ is not SmartEditTool
    assert isinstance(by_name["glob_files"], GlobTool)
    assert by_name["glob_files"].__class__ is not GlobTool
    assert isinstance(by_name["grep_content"], GrepTool)
    assert by_name["grep_content"].__class__ is not GrepTool


def test_sandbox_disabled_default_tools_keep_host_filesystem_and_command_tools():
    tools = create_default_tools(sandbox_session=None, memory_dir=None)
    by_name = {tool.name: tool for tool in tools}

    assert by_name["shell"].__class__ is ShellTool
    assert by_name["read_file"].__class__ is FileReadTool
    assert by_name["write_file"].__class__ is FileWriteTool
    assert by_name["smart_edit"].__class__ is SmartEditTool
    assert by_name["glob_files"].__class__ is GlobTool
    assert by_name["grep_content"].__class__ is GrepTool
    assert "web_search" in by_name
    assert "web_fetch" in by_name
    assert "conversation_search" in by_name
