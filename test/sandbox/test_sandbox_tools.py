from ouro.capabilities.tools.builtins.sandbox import (
    SandboxGlobTool,
    SandboxGrepTool,
    SandboxReadFileTool,
    SandboxShellTool,
    SandboxSmartEditTool,
    SandboxWriteFileTool,
)
from ouro.core.sandbox import SandboxCapabilities, SandboxExecResult


class FakeSandboxSession:
    id = "fake"
    provider = "fake"
    capabilities = SandboxCapabilities()

    def __init__(self):
        self.files = {"/workspace/app.py": "def hello():\n    return 'hi'\n"}
        self.commands = []

    async def start(self):
        pass

    async def exec(self, command, *, cwd=None, env=None, timeout=None):
        self.commands.append((command, cwd, timeout))
        return SandboxExecResult(stdout="ok\n", stderr="", exit_code=0)

    async def read_file(self, path, *, offset=0, limit=None):
        content = self.files[path]
        lines = content.splitlines(keepends=True)
        return "".join(lines[offset:] if limit is None else lines[offset : offset + limit])

    async def write_file(self, path, content):
        self.files[path] = content

    async def glob(self, pattern, *, path="."):
        return sorted(self.files)

    async def grep(
        self,
        pattern,
        *,
        path=".",
        mode="files_only",
        case_sensitive=True,
        file_pattern=None,
        context_lines=0,
        head_limit=None,
        offset=0,
    ):
        return "Found 1 files\n/workspace/app.py"

    async def close(self):
        pass


async def test_sandbox_shell_executes_in_session():
    session = FakeSandboxSession()
    result = await SandboxShellTool(session).execute("echo ok", timeout=5, cwd="/workspace")

    assert result == "ok\n"
    assert session.commands == [("echo ok", "/workspace", 5)]


async def test_sandbox_read_write_file():
    session = FakeSandboxSession()

    write_result = await SandboxWriteFileTool(session).execute("/workspace/new.txt", "hello")
    read_result = await SandboxReadFileTool(session).execute("/workspace/new.txt")

    assert "Successfully wrote" in write_result
    assert read_result == "hello"


async def test_sandbox_glob_and_grep():
    session = FakeSandboxSession()

    assert "/workspace/app.py" in await SandboxGlobTool(session).execute("**/*.py")
    assert "Found 1 files" in await SandboxGrepTool(session).execute("hello")


async def test_sandbox_smart_edit_dry_run_and_apply():
    session = FakeSandboxSession()
    tool = SandboxSmartEditTool(session)

    dry = await tool.execute(
        "/workspace/app.py",
        mode="diff_replace",
        old_code="return 'hi'",
        new_code="return 'bye'",
        dry_run=True,
    )
    assert "[DRY RUN]" in dry
    assert "bye" not in session.files["/workspace/app.py"]

    applied = await tool.execute(
        "/workspace/app.py",
        mode="diff_replace",
        old_code="return 'hi'",
        new_code="return 'bye'",
    )
    assert "Successfully edited" in applied
    assert "return 'bye'" in session.files["/workspace/app.py"]
