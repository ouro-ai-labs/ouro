"""Core tracing primitives for ouro runtime observability."""

from .context import get_current_run_id, get_current_span_id
from .events import TraceError, TraceEvent, TraceEventType, TraceStatus
from .exporters import (
    InMemoryTraceExporter,
    JSONLTraceExporter,
    NoOpTraceExporter,
    TraceExporter,
)
from .tracer import NoOpSpan, Span, Tracer, sanitize_attributes, span

__all__ = [
    "InMemoryTraceExporter",
    "JSONLTraceExporter",
    "NoOpSpan",
    "NoOpTraceExporter",
    "Span",
    "TraceError",
    "TraceEvent",
    "TraceEventType",
    "TraceExporter",
    "TraceStatus",
    "Tracer",
    "get_current_run_id",
    "get_current_span_id",
    "sanitize_attributes",
    "span",
]
