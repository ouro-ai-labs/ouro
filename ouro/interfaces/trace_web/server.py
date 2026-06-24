"""Local aiohttp web monitor for ouro trace databases."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from aiohttp import web

from ouro.config import Config
from ouro.core.tracing import resolve_sqlite_trace_db_path


@dataclass(frozen=True)
class TraceRunSummary:
    run_id: str
    started_at: str
    last_event_at: str
    status: str
    duration_ms: int | None
    llm_calls: int
    tool_calls: int
    event_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "last_event_at": self.last_event_at,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "event_count": self.event_count,
        }


def configured_trace_db_path() -> Path:
    """Resolve the configured SQLite trace DB path for the web monitor."""
    if Config.TRACE_STORAGE_DIALECT != "sqlite":
        raise ValueError(
            "Only TRACE_STORAGE_DIALECT=sqlite is supported by the local trace monitor."
        )
    return resolve_sqlite_trace_db_path(
        db_path=Config.TRACE_DB_PATH,
        database_url=Config.TRACE_DATABASE_URL or None,
    )


def create_app(db_path: str | Path | None = None) -> web.Application:
    """Create the trace monitor aiohttp app."""
    app = web.Application()
    app["trace_db_path"] = (
        Path(db_path).expanduser() if db_path is not None else configured_trace_db_path()
    )
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/runs", handle_runs)
    app.router.add_get("/api/runs/latest", handle_latest_run)
    app.router.add_get("/api/runs/{run_id}", handle_run_detail)
    app.router.add_get("/static/{name}", handle_static)
    return app


async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=_read_static_text("index.html"), content_type="text/html")


async def handle_static(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    if name not in {"app.js", "style.css"}:
        raise web.HTTPNotFound(text="static asset not found")
    content_type = "application/javascript" if name.endswith(".js") else "text/css"
    return web.Response(text=_read_static_text(name), content_type=content_type)


async def handle_runs(request: web.Request) -> web.Response:
    limit = _parse_limit(request.query.get("limit"))
    db_path = request.app["trace_db_path"]
    runs = await asyncio.to_thread(list_runs, db_path, limit)
    return web.json_response({"runs": [run.to_dict() for run in runs]})


async def handle_latest_run(request: web.Request) -> web.Response:
    db_path = request.app["trace_db_path"]
    run_id = await asyncio.to_thread(get_latest_run_id, db_path)
    if run_id is None:
        return web.json_response({"run": None, "events": []})
    events = await asyncio.to_thread(get_run_events, db_path, run_id)
    return web.json_response({"run_id": run_id, "events": events})


async def handle_run_detail(request: web.Request) -> web.Response:
    db_path = request.app["trace_db_path"]
    run_id = request.match_info["run_id"]
    events = await asyncio.to_thread(get_run_events, db_path, run_id)
    if not events:
        raise web.HTTPNotFound(text=f"run not found: {run_id}")
    return web.json_response({"run_id": run_id, "events": events})


def list_runs(db_path: str | Path, limit: int = 50) -> list[TraceRunSummary]:
    """Return recent trace run summaries from a SQLite trace DB."""
    path = Path(db_path).expanduser()
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                run_id,
                MIN(timestamp) AS started_at,
                MAX(timestamp) AS last_event_at,
                COUNT(*) AS event_count,
                COUNT(DISTINCT CASE WHEN event_type = 'llm_call' THEN span_id END) AS llm_calls,
                COUNT(DISTINCT CASE WHEN event_type = 'tool_call' THEN span_id END) AS tool_calls,
                MAX(CASE WHEN event_type = 'run' AND status IN ('completed', 'failed') THEN status END) AS terminal_status,
                MAX(CASE WHEN event_type = 'run' AND status IN ('completed', 'failed') THEN duration_ms END) AS duration_ms,
                MAX(rowid) AS last_sequence
            FROM trace_events
            GROUP BY run_id
            ORDER BY last_sequence DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        TraceRunSummary(
            run_id=row["run_id"],
            started_at=row["started_at"],
            last_event_at=row["last_event_at"],
            status=row["terminal_status"] or "running",
            duration_ms=row["duration_ms"],
            llm_calls=row["llm_calls"] or 0,
            tool_calls=row["tool_calls"] or 0,
            event_count=row["event_count"],
        )
        for row in rows
    ]


def get_latest_run_id(db_path: str | Path) -> str | None:
    """Return the most recently updated run ID, if any."""
    path = Path(db_path).expanduser()
    if not path.exists():
        return None
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT run_id
            FROM trace_events
            GROUP BY run_id
            ORDER BY MAX(rowid) DESC
            LIMIT 1
            """
        ).fetchone()
    return row[0] if row else None


def get_run_events(db_path: str | Path, run_id: str) -> list[dict[str, Any]]:
    """Return all trace events for a run as JSON-ready dictionaries."""
    path = Path(db_path).expanduser()
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                rowid AS sequence,
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
            FROM trace_events
            WHERE run_id = ?
            ORDER BY rowid
            """,
            (run_id,),
        ).fetchall()
    return [_event_row_to_dict(row) for row in rows]


def _event_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    columns = row.keys()
    event = {key: row[key] for key in columns if key not in _JSON_COLUMNS}
    event["attributes"] = _loads_json(row["attributes_json"], {})
    event["error"] = _loads_json(row["error_json"], None)
    event["links"] = _loads_json(row["links_json"], [])
    return event


def _loads_json(raw: str | None, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _parse_limit(raw: str | None) -> int:
    if raw is None:
        return 50
    try:
        return min(max(int(raw), 1), 200)
    except ValueError:
        return 50


def _read_static_text(name: str) -> str:
    return resources.files(__package__).joinpath("static", name).read_text(encoding="utf-8")


_JSON_COLUMNS = {"attributes_json", "error_json", "links_json"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the local ouro trace web monitor")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind (default: 8765)")
    parser.add_argument("--db", type=str, help="SQLite trace DB path (defaults to TRACE_DB_PATH)")
    args = parser.parse_args()

    app = create_app(args.db)
    print(f"Starting ouro trace monitor on http://{args.host}:{args.port}")
    print(f"Trace DB: {app['trace_db_path']}")
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
