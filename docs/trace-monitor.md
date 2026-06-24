# Trace Monitor

ouro can write opt-in agent traces to the configured SQLite trace database and show them in a local web monitor.

## Capture traces

Tracing is disabled by default. Enable it per run:

```bash
ouro --task "Summarize this README" --trace
```

By default, trace events are written to:

```text
~/.ouro/trace.db
```

Configure the location in `~/.ouro/config`:

```ini
TRACE_STORAGE_DIALECT=sqlite
TRACE_DB_PATH=~/.ouro/trace.db
TRACE_DATABASE_URL=
```

## Start the local monitor

```bash
ouro-trace-monitor
```

Then open:

```text
http://127.0.0.1:8765
```

Useful options:

```bash
ouro-trace-monitor --host 127.0.0.1 --port 8765
ouro-trace-monitor --db /path/to/trace.db
```

The web UI shows:

- recent runs
- run status and duration
- LLM/tool call counts
- trace tree for the selected run
- raw event metadata for selected spans

The first version polls the SQLite database every few seconds. WebSocket live streaming and swarm/task graph visualizations are planned future improvements.
