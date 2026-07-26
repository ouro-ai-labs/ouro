"""Shared sandbox session helpers."""

from __future__ import annotations

import base64
import json
import shlex
import textwrap
from abc import ABC, abstractmethod
from collections.abc import Sequence

from ouro.core.sandbox import SandboxCapabilities, SandboxExecResult

from ..manager import SandboxProfile


class SandboxProviderError(RuntimeError):
    """Raised when a sandbox provider cannot be used."""


class ExecOnlySandboxSession(ABC):
    """Base class that implements file/search helpers on top of exec."""

    capabilities = SandboxCapabilities(
        exec=True, read_file=True, write_file=True, glob=True, grep=True
    )

    def __init__(self, profile: SandboxProfile):
        self.profile = profile
        self.id = profile.sandbox_id
        self.provider = profile.provider
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await self._start_provider()
        self._started = True

    @abstractmethod
    async def _start_provider(self) -> None: ...

    @abstractmethod
    async def _exec_provider(
        self,
        command: str | list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> SandboxExecResult: ...

    async def exec(
        self,
        command: str | list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> SandboxExecResult:
        await self.start()
        return await self._exec_provider(command, cwd=cwd, env=env, timeout=timeout)

    async def read_file(self, path: str, *, offset: int = 0, limit: int | None = None) -> str:
        payload = {
            "path": path,
            "offset": max(0, int(offset or 0)),
            "limit": limit if limit is None else max(0, int(limit)),
        }
        script = r"""
import json, pathlib, sys
p = json.loads(sys.stdin.read())
path = pathlib.Path(p["path"])
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
offset = p.get("offset") or 0
limit = p.get("limit")
if limit is None:
    sys.stdout.write("".join(lines[offset:]))
else:
    selected = lines[offset:offset+limit]
    if offset > 0 or offset + limit < len(lines):
        sys.stdout.write(f"[Lines {offset+1}-{min(offset+limit, len(lines))} of {len(lines)}]\n")
    sys.stdout.write("".join(selected))
"""
        result = await self._run_python_stdin(
            script, json.dumps(payload), cwd=self.profile.working_dir
        )
        if result.exit_code != 0:
            raise SandboxProviderError(result.stderr or result.stdout or f"Failed to read {path}")
        return result.stdout

    async def write_file(self, path: str, content: str) -> None:
        payload = {"path": path, "content_b64": base64.b64encode(content.encode()).decode("ascii")}
        script = r"""
import base64, json, pathlib, sys
p = json.loads(sys.stdin.read())
path = pathlib.Path(p["path"])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(base64.b64decode(p["content_b64"]).decode("utf-8"), encoding="utf-8")
"""
        result = await self._run_python_stdin(
            script, json.dumps(payload), cwd=self.profile.working_dir
        )
        if result.exit_code != 0:
            raise SandboxProviderError(result.stderr or result.stdout or f"Failed to write {path}")

    async def glob(self, pattern: str, *, path: str = ".") -> list[str]:
        payload = {"pattern": pattern, "path": path}
        script = r"""
import json, pathlib, sys
p = json.loads(sys.stdin.read())
base = pathlib.Path(p["path"])
if not base.exists():
    print(json.dumps({"error": f"Path does not exist: {p['path']}"}))
    sys.exit(2)
print(json.dumps({"matches": sorted(str(x) for x in base.glob(p["pattern"]))}))
"""
        result = await self._run_python_stdin(
            script, json.dumps(payload), cwd=self.profile.working_dir
        )
        if result.exit_code != 0:
            raise SandboxProviderError(result.stderr or result.stdout or "Glob failed")
        data = json.loads(result.stdout or "{}")
        if data.get("error"):
            raise SandboxProviderError(str(data["error"]))
        return [str(item) for item in data.get("matches", [])]

    async def grep(
        self,
        pattern: str,
        *,
        path: str = ".",
        mode: str = "files_only",
        case_sensitive: bool = True,
        file_pattern: str | None = None,
        context_lines: int = 0,
        head_limit: int | None = None,
        offset: int = 0,
    ) -> str:
        payload = {
            "pattern": pattern,
            "path": path,
            "mode": mode,
            "case_sensitive": case_sensitive,
            "file_pattern": file_pattern,
            "context_lines": max(0, int(context_lines or 0)),
            "head_limit": 250 if head_limit is None else int(head_limit),
            "offset": max(0, int(offset or 0)),
        }
        script = r"""
import fnmatch, json, pathlib, re, sys
p = json.loads(sys.stdin.read())
base = pathlib.Path(p["path"])
if not base.exists():
    print(f"Error: Path does not exist: {p['path']}")
    sys.exit(0)
flags = 0 if p["case_sensitive"] else re.IGNORECASE
try:
    rx = re.compile(p["pattern"], flags)
except re.error as e:
    print(f"Error: Invalid regex pattern: {e}")
    sys.exit(0)
files = [x for x in base.rglob("*") if x.is_file()]
fp = p.get("file_pattern")
if fp:
    files = [x for x in files if fnmatch.fnmatch(str(x), fp) or fnmatch.fnmatch(x.name, fp)]
mode = p.get("mode") or "files_only"
items = []
for f in sorted(files):
    try:
        lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        continue
    matches = [(i, line) for i, line in enumerate(lines, 1) if rx.search(line)]
    if not matches:
        continue
    if mode == "files_only":
        items.append(str(f))
    elif mode == "count":
        items.append(f"{f}: {len(matches)}")
    else:
        ctx = p.get("context_lines") or 0
        for lineno, line in matches:
            start = max(1, lineno - ctx)
            end = min(len(lines), lineno + ctx)
            for n in range(start, end + 1):
                prefix = ":" if n == lineno else "-"
                items.append(f"{f}:{n}{prefix}{lines[n-1]}")
head = p.get("head_limit")
off = p.get("offset") or 0
sliced = items[off:] if head == 0 else items[off:off+head]
truncated = False if head == 0 else len(items) - off > head
noun = "files" if mode in {"files_only", "count"} else "matching lines"
if truncated:
    print(f"Found {len(items)} {noun} (showing {len(sliced)}, use offset={off + head} to see more)")
else:
    print(f"Found {len(items)} {noun}")
if sliced:
    print("\n".join(sliced))
"""
        result = await self._run_python_stdin(
            script, json.dumps(payload), cwd=self.profile.working_dir
        )
        return (result.stdout + result.stderr).strip()

    async def _run_python_stdin(
        self, script: str, stdin_text: str, *, cwd: str | None = None
    ) -> SandboxExecResult:
        command = _python_stdin_command(script, stdin_text)
        return await self._exec_provider(command, cwd=cwd, timeout=120)

    async def close(self) -> None:
        self._started = False


def _python_stdin_command(script: str, stdin_text: str) -> str:
    script_arg = shlex.quote(textwrap.dedent(script).strip())
    stdin_arg = shlex.quote(stdin_text)
    return f"printf %s {stdin_arg} | python -c {script_arg}"


def normalize_exec_result(result: object) -> SandboxExecResult:
    """Best-effort conversion from provider SDK result objects."""

    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    exit_code = getattr(result, "exit_code", None)
    if exit_code is None:
        exit_code = getattr(result, "returncode", None)
    if exit_code is None:
        exit_code = getattr(result, "code", 0)
    return SandboxExecResult(stdout=str(stdout), stderr=str(stderr), exit_code=int(exit_code or 0))


def split_command(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        return ["sh", "-lc", command]
    return [str(part) for part in command]
