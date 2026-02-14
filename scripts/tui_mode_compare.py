#!/usr/bin/env python3
"""Compare core interactive behavior across TUI modes.

Modes covered:
- default (no OURO_TUI)
- ptk      (OURO_TUI=ptk)
- ptk2     (OURO_TUI=ptk2)

Why this script uses PTY + marker matching:
- PTY simulates a real terminal; plain pipes miss TUI redraw behavior.
- We capture output incrementally (since each command send) to avoid matching
  stale text from previous steps.
- We assert with ANSI-tolerant matching (raw + compacted text) because TUI
  redraw can split words/spacing differently across modes.

This script is intentionally a lightweight smoke parity check, not a full e2e
test harness. It verifies the primary command flow and exits non-zero on any
detected regression.
"""

from __future__ import annotations

import contextlib
import os
import pty
import re
import select
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


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
class StepResult:
    step: str
    ok: bool
    latency_s: Optional[float] = None
    detail: str = ""


@dataclass
class ModeResult:
    mode: str
    ok: bool
    startup_s: Optional[float]
    total_s: float
    steps: list[StepResult] = field(default_factory=list)
    error_tail: str = ""


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
        self.text_tail = ""

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
        decoded = data.decode("utf-8", errors="ignore")
        self.text_tail = (self.text_tail + strip_ansi(decoded))[-300000:]

    def wait_for(
        self,
        patterns: Iterable[str],
        timeout: float,
        since_len: Optional[int] = None,
    ) -> tuple[bool, str]:
        patterns = list(patterns)
        compact_patterns = [compact(p) for p in patterns]
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            self.read_some(0.05)
            hay_all = self.text_tail
            hay = hay_all[since_len:] if since_len is not None else hay_all
            hay_compact = compact(hay)

            for pattern, pattern_compact in zip(patterns, compact_patterns):
                if pattern in hay or pattern_compact in hay_compact:
                    return True, pattern

            if self.proc.poll() is not None:
                return False, f"process exited rc={self.proc.returncode}"

        return False, f"timeout waiting for {patterns}"

    def send(self, text: str) -> None:
        os.write(self.master_fd, text.encode("utf-8"))

    def is_alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        try:
            if self.is_alive():
                self.send("/exit\r")
                start = time.monotonic()
                while self.is_alive() and time.monotonic() - start < 2.5:
                    self.read_some(0.05)
                if self.is_alive():
                    self.proc.terminate()
        finally:
            with contextlib.suppress(OSError):
                os.close(self.master_fd)


def run_mode(mode: str) -> ModeResult:
    session = PtySession(mode)
    start_time = time.monotonic()
    steps: list[StepResult] = []

    def run_step(
        step: str,
        payload: str,
        markers: list[str],
        timeout: float,
    ) -> bool:
        since = len(session.text_tail)
        t0 = time.monotonic()
        session.send(payload)
        ok, detail = session.wait_for(markers, timeout=timeout, since_len=since)
        latency = time.monotonic() - t0
        steps.append(StepResult(step=step, ok=ok, latency_s=latency if ok else None, detail=detail))
        return ok

    try:
        since = len(session.text_tail)
        ok, detail = session.wait_for(
            ["Interactive mode started. Type your message or use commands."],
            timeout=30.0,
            since_len=since,
        )
        startup_s = time.monotonic() - start_time if ok else None
        steps.append(StepResult("startup", ok, startup_s if ok else None, detail))
        if not ok:
            return ModeResult(mode, False, startup_s, time.monotonic() - start_time, steps, session.text_tail[-6000:])

        if not run_step("help", "/help\r", ["Available Commands:", "Keyboard", "model edit"], 10.0):
            return ModeResult(mode, False, startup_s, time.monotonic() - start_time, steps, session.text_tail[-6000:])

        # Keyboard scroll fallback smoke in case physical mouse isn't available.
        session.send("\x1b[5~\x1b[6~")
        time.sleep(0.1)
        if not session.is_alive():
            steps.append(StepResult("scroll_keys_alive", False, None, "process died after page up/down"))
            return ModeResult(mode, False, startup_s, time.monotonic() - start_time, steps, session.text_tail[-6000:])

        basic_plan: list[tuple[str, str, list[str], float]] = [
            ("stats", "/stats\r", ["Memory Statistics"], 8.0),
            ("resume", "/resume\r", ["Recent Sessions:", "No saved sessions found.", "Usage: /resume"], 8.0),
            ("theme", "/theme\r", ["Switched to light theme", "Switched to dark theme"], 8.0),
            ("verbose", "/verbose\r", ["Verbose thinking display"], 8.0),
            ("compact", "/compact\r", ["Nothing to compress.", "No messages to compress", "Compressed "], 10.0),
        ]
        for step, payload, markers, timeout in basic_plan:
            if not run_step(step, payload, markers, timeout):
                return ModeResult(mode, False, startup_s, time.monotonic() - start_time, steps, session.text_tail[-6000:])

        if not run_step("model_open", "/model\r", ["Select Model"], 8.0):
            return ModeResult(mode, False, startup_s, time.monotonic() - start_time, steps, session.text_tail[-6000:])
        if not run_step("model_pick", "\r", ["Switched to model:", "Failed to switch to model"], 8.0):
            return ModeResult(mode, False, startup_s, time.monotonic() - start_time, steps, session.text_tail[-6000:])

        if not run_step("skills_open", "/skills\r", ["Choose an action", "Skills\nChoose an action"], 8.0):
            return ModeResult(mode, False, startup_s, time.monotonic() - start_time, steps, session.text_tail[-6000:])
        if not run_step(
            "skills_pick",
            "\r",
            ["Installed Skills:", "No installed skills found", "skill-installer", "skill-creator"],
            8.0,
        ):
            return ModeResult(mode, False, startup_s, time.monotonic() - start_time, steps, session.text_tail[-6000:])

        if not run_step("reset", "/reset\r", ["Memory cleared. Starting fresh conversation."], 8.0):
            return ModeResult(mode, False, startup_s, time.monotonic() - start_time, steps, session.text_tail[-6000:])
        if not run_step("exit", "/exit\r", ["Exiting interactive mode. Goodbye!"], 8.0):
            return ModeResult(mode, False, startup_s, time.monotonic() - start_time, steps, session.text_tail[-6000:])

        # Ensure process exits after /exit.
        wait_start = time.monotonic()
        while session.is_alive() and time.monotonic() - wait_start < 5.0:
            session.read_some(0.05)
        if session.is_alive():
            steps.append(StepResult("process_exit", False, None, "did not exit after /exit"))
            return ModeResult(mode, False, startup_s, time.monotonic() - start_time, steps, session.text_tail[-6000:])

        return ModeResult(mode, True, startup_s, time.monotonic() - start_time, steps)
    finally:
        session.close()


def main() -> int:
    modes = ["default", "ptk", "ptk2"]
    results = [run_mode(mode) for mode in modes]

    print("=== SUMMARY ===")
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        startup = f"{result.startup_s:.3f}s" if result.startup_s is not None else "N/A"
        print(f"{result.mode:7} {status:4} startup={startup} total={result.total_s:.3f}s")

    print("\n=== STEP DETAILS ===")
    for result in results:
        print(f"\n[{result.mode}] ok={result.ok}")
        for step in result.steps:
            latency = f"{step.latency_s:.3f}s" if step.latency_s is not None else "N/A"
            print(f" - {step.step:12} {'OK' if step.ok else 'FAIL':4} {latency:>8}  {step.detail}")
        if result.error_tail:
            print(" --- tail ---")
            print(result.error_tail[-2400:])

    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
