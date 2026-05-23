"""Recall memory — keyword search over historical conversation messages.

SQLite FTS5 backed; no embedder required. Built on the OS-paging idea from
Letta/MemGPT: keep recent messages in context, page older messages out to
an indexed store, search them on demand via a tool call.
"""

from ouro.capabilities.memory.recall.sqlite_fts import RecallIndex

__all__ = ["RecallIndex"]
