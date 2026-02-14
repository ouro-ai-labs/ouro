#!/usr/bin/env python3
"""Benchmark startup/help/exit latency across TUI modes.

Method notes:
- Uses PTY for realistic TUI startup/render timing.
- Runs multiple samples per mode and reports mean/p50/min/max to reduce
  single-run noise.
- Startup can have occasional outliers due to external initialization
  (e.g. network fallback in dependencies), so p50 is often a better signal
  than mean.
"""

from __future__ import annotations

import contextlib
import os
import pty
import re
import select
import statistics
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


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


@dataclass
class Sample:
    startup_s: float
    help_s: float
    exit_s: float


class PtySession:
    def __init__(self, mode: str) -> None:
        env = os.environ.copy()
        env.pop("OURO_TUI", None)
        if mode != "default":
            env["OURO_TUI"] = mode

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
        self.buffer = ""

    def read_some(self, timeout: float = 0.05) -> None:
        ready, _, _ = select.select([self.master_fd], [], [], timeout)
        if not ready:
            return
        try:
            data = os.read(self.master_fd, 65536)
        except OSError:
            return
        if not data:
            return
        self.buffer = (self.buffer + strip_ansi(data.decode("utf-8", errors="ignore")))[-220000:]

    def wait_for(self, patterns: list[str], timeout: float, since_len: int) -> bool:
        compact_patterns = [compact(p) for p in patterns]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.read_some(0.05)
            hay = self.buffer[since_len:]
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


def run_once(mode: str) -> Optional[Sample]:
    session = PtySession(mode)
    try:
        start_idx = len(session.buffer)
        t0 = time.monotonic()
        if not session.wait_for(
            ["Interactive mode started. Type your message or use commands."],
            timeout=30,
            since_len=start_idx,
        ):
            return None
        startup_s = time.monotonic() - t0

        help_idx = len(session.buffer)
        t1 = time.monotonic()
        session.send("/help\r")
        if not session.wait_for(["Available Commands:", "Keyboard", "model edit"], timeout=10, since_len=help_idx):
            return None
        help_s = time.monotonic() - t1

        exit_idx = len(session.buffer)
        t2 = time.monotonic()
        session.send("/exit\r")
        if not session.wait_for(["Exiting interactive mode. Goodbye!"], timeout=10, since_len=exit_idx):
            return None
        exit_s = time.monotonic() - t2

        return Sample(startup_s=startup_s, help_s=help_s, exit_s=exit_s)
    finally:
        session.close()


def summarize(samples: list[float]) -> str:
    return (
        f"{statistics.mean(samples):.3f} "
        f"(p50 {statistics.median(samples):.3f}, min {min(samples):.3f}, max {max(samples):.3f})"
    )


def main() -> int:
    modes = ["default", "ptk", "ptk2"]
    runs = 5

    for mode in modes:
        pass_count = 0
        startups: list[float] = []
        helps: list[float] = []
        exits: list[float] = []

        for _ in range(runs):
            sample = run_once(mode)
            if sample is None:
                continue
            pass_count += 1
            startups.append(sample.startup_s)
            helps.append(sample.help_s)
            exits.append(sample.exit_s)

        fail_count = runs - pass_count
        print(f"mode={mode} runs={runs} pass={pass_count} fail={fail_count}")
        if pass_count:
            print(f"  startup_s : {summarize(startups)}")
            print(f"  help_s    : {summarize(helps)}")
            print(f"  exit_s    : {summarize(exits)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
