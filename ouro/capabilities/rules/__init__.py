"""Tool-aware loop rules (capabilities layer).

These implement the core ``ouro.core.loop.Rule`` per-tool-call contract but, unlike
the generic rules in ``ouro.core.loop.rules``, they know about specific tool names
and argument shapes — so they live here, above the core boundary.
"""

from .read_before_write import ReadBeforeWriteRule

__all__ = ["ReadBeforeWriteRule"]
