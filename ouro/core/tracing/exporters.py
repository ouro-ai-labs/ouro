"""Trace exporters for local testing and JSONL persistence."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Protocol

from .events import TraceEvent


class TraceExporter(Protocol):
    """Receives trace events emitted by a tracer."""

    async def export(self, event: TraceEvent) -> None: ...


class NoOpTraceExporter:
    """Exporter that intentionally drops every event."""

    async def export(self, event: TraceEvent) -> None:
        return None


class InMemoryTraceExporter:
    """Exporter useful for deterministic tests."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def export(self, event: TraceEvent) -> None:
        self.events.append(event)


class JSONLTraceExporter:
    """Append trace events to a newline-delimited JSON file.

    File writes are protected by an async lock so concurrent spans do not
    interleave writes. The implementation performs small synchronous writes;
    it is intended for local/debug export and should be wrapped/buffered before
    use on high-volume hot paths.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def export(self, event: TraceEvent) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
