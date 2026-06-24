"""Async-safe tracer and span primitives."""

from __future__ import annotations

import traceback
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from time import perf_counter
from types import TracebackType
from typing import Any, Self

from . import context
from .events import TraceError, TraceEvent, TraceStatus, utc_now
from .exporters import NoOpTraceExporter, TraceExporter

_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "auth_header",
    "access_token",
    "refresh_token",
    "id_token",
    "secret",
    "password",
}
_SECRET_SUFFIXES = ("_api_key", "_secret", "_password", "_access_token", "_refresh_token")
_BLOB_KEYS = {"image", "image_url", "base64", "b64_json", "audio", "video"}
_DEFAULT_MAX_STRING_LENGTH = 65536
_DEFAULT_MAX_ATTRIBUTES = 64


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _is_blob_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _BLOB_KEYS or lowered.endswith(("_base64", "_b64", "_blob"))


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _SECRET_KEYS or any(lowered.endswith(suffix) for suffix in _SECRET_SUFFIXES)


def _sanitize_value(value: Any, *, max_string_length: int) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if len(value) <= max_string_length:
            return value
        return value[:max_string_length] + "…[truncated]"
    if isinstance(value, Mapping):
        return sanitize_attributes(value, max_string_length=max_string_length)
    if isinstance(value, list | tuple):
        return [_sanitize_value(item, max_string_length=max_string_length) for item in value]
    return repr(value)


def sanitize_attributes(
    attributes: Mapping[str, Any] | None,
    *,
    max_string_length: int = _DEFAULT_MAX_STRING_LENGTH,
    max_attributes: int = _DEFAULT_MAX_ATTRIBUTES,
) -> dict[str, Any]:
    """Return redacted and bounded trace attributes."""
    if not attributes:
        return {}

    sanitized: dict[str, Any] = {}
    for index, (key, value) in enumerate(attributes.items()):
        if index >= max_attributes:
            sanitized["trace.attributes.truncated"] = True
            break
        string_key = str(key)
        if _is_secret_key(string_key):
            sanitized[string_key] = "[redacted]"
        elif _is_blob_key(string_key):
            sanitized[string_key] = "[omitted binary/blob]"
        else:
            sanitized[string_key] = _sanitize_value(value, max_string_length=max_string_length)
    return sanitized


class Tracer:
    """Create trace spans and emit structured events."""

    def __init__(
        self,
        exporter: TraceExporter | None = None,
        *,
        enabled: bool = True,
        run_id: str | None = None,
        max_string_length: int = _DEFAULT_MAX_STRING_LENGTH,
    ) -> None:
        self.exporter = exporter or NoOpTraceExporter()
        self.enabled = enabled
        self.run_id = run_id or _new_id("run")
        self.max_string_length = max_string_length

    def span(
        self,
        event_type: str,
        name: str,
        *,
        attributes: Mapping[str, Any] | None = None,
        agent_id: str | None = None,
        task_id: str | None = None,
        links: tuple[str, ...] = (),
    ) -> Span | NoOpSpan:
        """Create a span context manager."""
        if not self.enabled:
            return NoOpSpan()
        return Span(
            tracer=self,
            event_type=event_type,
            name=name,
            attributes=attributes,
            agent_id=agent_id,
            task_id=task_id,
            links=links,
        )

    async def emit_event(
        self,
        event_type: str,
        name: str,
        *,
        attributes: Mapping[str, Any] | None = None,
        status: TraceStatus = "event",
        agent_id: str | None = None,
        task_id: str | None = None,
        links: tuple[str, ...] = (),
    ) -> None:
        """Emit a standalone trace event under the current span context."""
        if not self.enabled:
            return
        run_id = context.get_current_run_id() or self.run_id
        span_id = context.get_current_span_id() or _new_id("span")
        event = TraceEvent(
            event_id=_new_id("evt"),
            run_id=run_id,
            span_id=span_id,
            parent_span_id=context.get_current_span_id(),
            timestamp=utc_now(),
            event_type=event_type,
            name=name,
            status=status,
            attributes=sanitize_attributes(attributes, max_string_length=self.max_string_length),
            agent_id=agent_id,
            task_id=task_id,
            links=links,
        )
        await self._export(event)

    async def _export(self, event: TraceEvent) -> None:
        try:
            await self.exporter.export(event)
        except Exception:
            # Tracing is best-effort by default and must not fail user work.
            return


class Span:
    """Async context manager representing a traced operation."""

    def __init__(
        self,
        *,
        tracer: Tracer,
        event_type: str,
        name: str,
        attributes: Mapping[str, Any] | None,
        agent_id: str | None,
        task_id: str | None,
        links: tuple[str, ...],
    ) -> None:
        self.tracer = tracer
        self.event_type = event_type
        self.name = name
        self.attributes = sanitize_attributes(
            attributes, max_string_length=tracer.max_string_length
        )
        self.agent_id = agent_id
        self.task_id = task_id
        self.links = links
        self.span_id = _new_id("span")
        self.parent_span_id: str | None = None
        self.run_id = tracer.run_id
        self._start = 0.0
        self._run_token: Any = None
        self._span_token: Any = None

    def set_attributes(self, attributes: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        """Merge additional sanitized attributes into future span events."""
        merged: dict[str, Any] = {}
        if attributes:
            merged.update(attributes)
        merged.update(kwargs)
        self.attributes.update(
            sanitize_attributes(merged, max_string_length=self.tracer.max_string_length)
        )

    async def __aenter__(self) -> Self:
        self.parent_span_id = context.get_current_span_id()
        self.run_id = context.get_current_run_id() or self.tracer.run_id
        self._run_token = context._current_run_id.set(self.run_id)
        self._span_token = context._current_span_id.set(self.span_id)
        self._start = perf_counter()
        await self._emit("started")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        duration_ms = int((perf_counter() - self._start) * 1000)
        if exc is None:
            await self._emit("completed", duration_ms=duration_ms)
        else:
            self.set_attributes(
                {"error.traceback": "".join(traceback.format_exception(exc_type, exc, tb))}
            )
            await self._emit(
                "failed",
                duration_ms=duration_ms,
                error=TraceError(type=type(exc).__name__, message=str(exc)),
            )
        if self._span_token is not None:
            context._current_span_id.reset(self._span_token)
        if self._run_token is not None:
            context._current_run_id.reset(self._run_token)
        return False

    async def _emit(
        self,
        status: TraceStatus,
        *,
        duration_ms: int | None = None,
        error: TraceError | None = None,
    ) -> None:
        await self.tracer._export(
            TraceEvent(
                event_id=_new_id("evt"),
                run_id=self.run_id,
                span_id=self.span_id,
                parent_span_id=self.parent_span_id,
                timestamp=utc_now(),
                event_type=self.event_type,
                name=self.name,
                status=status,
                attributes=self.attributes,
                agent_id=self.agent_id,
                task_id=self.task_id,
                duration_ms=duration_ms,
                error=error,
                links=self.links,
            )
        )


class NoOpSpan:
    """Span context manager used when tracing is disabled."""

    def set_attributes(self, attributes: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        return None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False


@asynccontextmanager
async def span(
    tracer: Tracer,
    event_type: str,
    name: str,
    **kwargs: Any,
) -> AsyncIterator[Span | NoOpSpan]:
    """Convenience async context manager around ``Tracer.span``."""
    async with tracer.span(event_type, name, **kwargs) as active_span:
        yield active_span
