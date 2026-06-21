"""Trace exporters for local testing, database persistence, and JSONL export."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

from .events import TraceEvent

_TRACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ms INTEGER,
    agent_id TEXT,
    task_id TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    error_json TEXT,
    links_json TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_trace_events_run_id ON trace_events(run_id);
CREATE INDEX IF NOT EXISTS idx_trace_events_span_id ON trace_events(span_id);
CREATE INDEX IF NOT EXISTS idx_trace_events_parent_span_id ON trace_events(parent_span_id);
CREATE INDEX IF NOT EXISTS idx_trace_events_timestamp ON trace_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_trace_events_type_status ON trace_events(event_type, status);
CREATE INDEX IF NOT EXISTS idx_trace_events_agent_task ON trace_events(agent_id, task_id);
"""


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


class SQLiteTraceExporter:
    """Persist trace events to a local SQLite database.

    This is the default durable trace store target for local ouro runs. Writes
    are serialized with an async lock and executed in a worker thread to avoid
    blocking the event loop with filesystem I/O.
    """

    def __init__(self, path: str | Path | None = None, *, database_url: str | None = None) -> None:
        self.path = resolve_sqlite_trace_db_path(db_path=path, database_url=database_url)
        self._lock = asyncio.Lock()
        self._initialized = False

    async def export(self, event: TraceEvent) -> None:
        async with self._lock:
            await asyncio.to_thread(self._export_sync, event)

    def _export_sync(self, event: TraceEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            if not self._initialized:
                connection.executescript(_TRACE_SCHEMA)
                self._initialized = True
            connection.execute(
                """
                INSERT OR REPLACE INTO trace_events (
                    event_id,
                    run_id,
                    span_id,
                    parent_span_id,
                    timestamp,
                    event_type,
                    name,
                    status,
                    duration_ms,
                    agent_id,
                    task_id,
                    attributes_json,
                    error_json,
                    links_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                trace_event_row(event),
            )
            connection.commit()


class JSONLTraceExporter:
    """Append trace events to a newline-delimited JSON file.

    JSONL is intended for local debugging, interchange, and monitor replay.
    Durable analysis should prefer the database exporter.
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


def default_trace_db_path() -> Path:
    """Return the default local trace database path."""
    return Path.home() / ".ouro" / "trace.db"


def resolve_sqlite_trace_db_path(
    *, db_path: str | Path | None = None, database_url: str | None = None
) -> Path:
    """Resolve configured SQLite trace storage into a local database path.

    Higher layers own configuration loading and should pass `TRACE_DB_PATH` as
    ``db_path`` or a SQLite ``TRACE_DATABASE_URL`` as ``database_url``. Core
    tracing intentionally does not import ``ouro.config``.
    """
    if database_url:
        parsed = urlparse(database_url)
        if parsed.scheme != "sqlite":
            raise ValueError(f"Unsupported SQLite trace database URL scheme: {parsed.scheme}")
        if parsed.netloc and parsed.netloc != "localhost":
            raise ValueError("SQLite trace database URLs must be local paths")
        if parsed.path in {"", "/"}:
            raise ValueError("SQLite trace database URL must include a database path")
        return Path(unquote(parsed.path)).expanduser()

    if db_path is not None:
        return Path(db_path).expanduser()

    return default_trace_db_path()


def trace_event_row(event: TraceEvent) -> tuple[object, ...]:
    """Return the SQLite row representation for a trace event."""
    timestamp = event.timestamp.astimezone().isoformat()
    return (
        event.event_id,
        event.run_id,
        event.span_id,
        event.parent_span_id,
        timestamp,
        event.event_type,
        event.name,
        event.status,
        event.duration_ms,
        event.agent_id,
        event.task_id,
        json.dumps(event.attributes, ensure_ascii=False, sort_keys=True),
        (
            json.dumps(event.error.to_dict(), ensure_ascii=False, sort_keys=True)
            if event.error is not None
            else None
        ),
        json.dumps(list(event.links), ensure_ascii=False, sort_keys=True),
    )
