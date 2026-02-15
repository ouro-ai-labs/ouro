#!/usr/bin/env python3
"""Benchmark redraw throughput under synthetic high-frequency output.

This benchmark exists to validate whether the PTK2 single-renderer refactor has
measurable benefits in "lots of output quickly" scenarios without requiring any
network/model calls.

How it works:
- Starts `ouro` in a PTY (real terminal behavior).
- Runs an internal-only command:
    /__bench_redraw chunks=... chunk_size=... delay_ms=...
- Measures wall time for the command to complete and CPU time consumed by the
  child process (user+sys), reporting mean/p50/min/max across runs.

Modes:
- default (no OURO_TUI)
- ptk2    (OURO_TUI=ptk2)

The internal command is gated behind OURO_INTERNAL_BENCH=1.
"""

from __future__ import annotations

import contextlib
import os
import pty
import re
import resource
import select
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)")
WHITESPACE_RE = re.compile(r"\s+")


def strip_ansi(text: str) -> str:
    text = OSC_RE.sub("", text)
    text = ANSI_RE.sub("", text)
    return text.replace("\r", "\n")


def compact(text: str) -> str:
    return WHITESPACE_RE.sub("", text)


def _rusage_children_seconds() -> float:
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(ru.ru_utime + ru.ru_stime)


class PtySession:
    def __init__(self, mode: str) -> None:
        env = os.environ.copy()
        env.pop("OURO_TUI", None)
        if mode != "default":
            env["OURO_TUI"] = mode

        env["OURO_INTERNAL_BENCH"] = "1"

        self._capture_path: str | None = None
        self._capture_pos = 0
        if mode == "ptk2":
            fd, path = tempfile.mkstemp(prefix="ouro-ptk2-capture-", suffix=".log")
            os.close(fd)
            self._capture_path = path
            env["PTK2_CAPTURE_PATH"] = path

        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd
        self.proc = subprocess.Popen(  # noqa: S603
            ["uv", "run", "ouro"],
            cwd=str(REPO_ROOT),
            env=env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)
        self.tail = ""

    def _read_capture(self) -> None:
        if not self._capture_path:
            return
        try:
            with open(self._capture_path, encoding="utf-8", errors="ignore") as f:
                f.seek(self._capture_pos)
                chunk = f.read()
                self._capture_pos = f.tell()
        except OSError:
            return
        if chunk:
            self.tail = (self.tail + chunk)[-400000:]

    def read_some(self, timeout: float = 0.05) -> None:
        ready, _, _ = select.select([self.master_fd], [], [], timeout)
        if ready:
            try:
                data = os.read(self.master_fd, 65536)
            except OSError:
                data = b""
            if data:
                decoded = data.decode("utf-8", errors="ignore")
                self.tail = (self.tail + strip_ansi(decoded))[-400000:]
        self._read_capture()

    def wait_for(self, patterns: list[str], timeout: float, since_len: int) -> bool:
        compact_patterns = [compact(p) for p in patterns]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.read_some(0.05)
            hay = self.tail[since_len:]
            hay_compact = compact(hay)
            for pattern, pattern_compact in zip(patterns, compact_patterns):
                if pattern in hay or pattern_compact in hay_compact:
                    return True
            if self.proc.poll() is not None:
                return False
        return False

    def send(self, text: str) -> None:
        os.write(self.master_fd, text.encode("utf-8"))

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                self.send("/exit\r")
                start = time.monotonic()
                while self.proc.poll() is None and time.monotonic() - start < 2:
                    self.read_some(0.05)
                if self.proc.poll() is None:
                    self.proc.terminate()
        finally:
            with contextlib.suppress(OSError):
                os.close(self.master_fd)
            if self._capture_path:
                with contextlib.suppress(OSError):
                    os.unlink(self._capture_path)


def summarize(samples: list[float]) -> str:
    return (
        f"{statistics.mean(samples):.3f} "
        f"(p50 {statistics.median(samples):.3f}, min {min(samples):.3f}, max {max(samples):.3f})"
    )


def run_once(mode: str, *, chunks: int, chunk_size: int, delay_ms: float) -> tuple[float, float] | None:
    cpu_before = _rusage_children_seconds()
    session = PtySession(mode)
    try:
        startup_idx = len(session.tail)
        if not session.wait_for(
            ["Interactive mode started. Type your message or use commands."],
            timeout=30,
            since_len=startup_idx,
        ):
            return None

        cmd = f"/__bench_redraw chunks={chunks} chunk_size={chunk_size} delay_ms={delay_ms:g}\r"
        bench_idx = len(session.tail)
        t0 = time.monotonic()
        session.send(cmd)
        ok = session.wait_for(["REDRAW_BENCH_DONE"], timeout=120.0, since_len=bench_idx)
        wall_s = time.monotonic() - t0
        if not ok:
            return None

        cpu_after = _rusage_children_seconds()
        cpu_s = max(0.0, cpu_after - cpu_before)
        return wall_s, cpu_s
    finally:
        session.close()


def main() -> int:
    runs = int(os.environ.get("REDRAW_BENCH_RUNS", "10"))
    chunks = int(os.environ.get("REDRAW_CHUNKS", "800"))
    chunk_size = int(os.environ.get("REDRAW_CHUNK_SIZE", "220"))
    delay_ms = float(os.environ.get("REDRAW_DELAY_MS", "0"))

    modes = ["default", "ptk2"]
    for mode in modes:
        wall_samples: list[float] = []
        cpu_samples: list[float] = []
        pass_count = 0

        for _ in range(runs):
            sample = run_once(mode, chunks=chunks, chunk_size=chunk_size, delay_ms=delay_ms)
            if sample is None:
                continue
            pass_count += 1
            wall_s, cpu_s = sample
            wall_samples.append(wall_s)
            cpu_samples.append(cpu_s)

        fail_count = runs - pass_count
        print(
            f"mode={mode} runs={runs} pass={pass_count} fail={fail_count} "
            f"chunks={chunks} chunk_size={chunk_size} delay_ms={delay_ms:g}"
        )
        if pass_count:
            print(f"  redraw_wall_s: {summarize(wall_samples)}")
            print(f"  redraw_cpu_s : {summarize(cpu_samples)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

