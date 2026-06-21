"""Context-local trace span state."""

from __future__ import annotations

from contextvars import ContextVar

_current_run_id: ContextVar[str | None] = ContextVar("ouro_trace_current_run_id", default=None)
_current_span_id: ContextVar[str | None] = ContextVar("ouro_trace_current_span_id", default=None)


def get_current_run_id() -> str | None:
    return _current_run_id.get()


def get_current_span_id() -> str | None:
    return _current_span_id.get()
