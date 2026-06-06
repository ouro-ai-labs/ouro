"""JSON-backed ProgressSink for machine-readable event streaming."""

from __future__ import annotations

import json
from contextlib import AbstractAsyncContextManager
from typing import Any

from ouro.core.loop import NullProgressSink


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

    def info(self, msg: str) -> None:
        self._emit({"type": "info", "message": msg})

    def event(self, kind: str, payload: dict[str, Any]) -> None:
        self._emit({"type": "event", "kind": kind, "payload": payload})

    def thinking(self, text: str) -> None:
        self._emit({"type": "thinking", "text": text})

    def assistant_message(self, content: Any) -> None:
        self._emit({"type": "assistant_message", "content": content})

    def tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        self._emit({"type": "tool_call", "name": name, "arguments": arguments})

    def tool_result(self, result: str) -> None:
        self._emit({"type": "tool_result", "result": result})

    def tool_blocked(self, name: str, arguments: dict[str, Any], reason: str) -> None:
        self._emit(
            {
                "type": "tool_blocked",
                "name": name,
                "arguments": arguments,
                "reason": reason,
            }
        )

    def final_answer(self, text: str) -> None:
        self._emit({"type": "final_answer", "text": text})

    def unfinished_answer(self, text: str) -> None:
        self._emit({"type": "unfinished_answer", "text": text})

    def spinner(self, label: str, title: str | None = None) -> AbstractAsyncContextManager[Any]:
        return self._null.spinner(label, title)

    def on_session_loaded(self, messages: list[Any]) -> None:
        self._emit({"type": "session_loaded", "count": len(messages)})
