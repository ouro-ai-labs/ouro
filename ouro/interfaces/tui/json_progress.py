"""JSON-backed ProgressSink for machine-readable event streaming."""

from __future__ import annotations

import json
from contextlib import AbstractAsyncContextManager
from typing import Any

from ouro.core.loop import NullProgressSink, ProgressEvent


class JsonProgressSink:
    """Progress sink that emits line-delimited JSON records."""

    def __init__(self, stream=None) -> None:
        self._stream = stream
        self._null = NullProgressSink()

    def _emit(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False)
        if self._stream is not None:
            self._stream.write(line + "\n")
            flush = getattr(self._stream, "flush", None)
            if callable(flush):
                flush()

    def emit(self, event: ProgressEvent) -> None:
        self._emit({"kind": event.kind, "payload": event.payload})

    def spinner(self, label: str, title: str | None = None) -> AbstractAsyncContextManager[Any]:
        return self._null.spinner(label, title)

    def on_session_loaded(self, messages: list[Any]) -> None:
        self.emit(ProgressEvent(kind="session_loaded", payload={"count": len(messages)}))
