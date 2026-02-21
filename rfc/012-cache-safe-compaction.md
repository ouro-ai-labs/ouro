# RFC 012: Cache-Safe Forking for Memory Compaction

- Status: Implemented
- Authors: luoyixin, Claude
- Date: 2026-02-20

## Summary

Move the LLM call for memory compression out of the compressor and into `_react_loop()`, so compaction reuses the same prefix (system prompt + tools + conversation) as normal turns and gets prompt cache hits. This reduces compaction cost by ~90% on cached prefixes.

## Problem

When ouro runs out of context window space, it compacts the conversation by summarizing it via an LLM call. Currently this compaction call uses a **bare user message** with no system prompt, tools, or conversation history — completely different from the main conversation's prefix:

```
Normal turn:    [system] [tools] [msg1] [msg2] ... [msgN] [user question]
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ cached prefix

Compaction call: [user: "Summarize these messages: {dump}"]
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ zero cache overlap
```

Since Anthropic's prompt caching matches by prefix, the compaction call gets **zero cache hits**, and the user pays full price for re-processing all those input tokens. For a 100k-token context, that's ~$0.30 per compaction at full input price vs ~$0.03 with cache reads.

### Concrete example

A typical coding session triggers 3-5 compressions. At 100k tokens per compaction:
- **Before**: 3 × $0.30 = $0.90 wasted on uncached compaction calls
- **After**: 3 × $0.03 = $0.09 (cache reads at 0.1× price)

## Goals

- Compaction LLM calls reuse the cached prefix (system prompt + tools + conversation)
- No changes to compression quality or strategy selection
- Backward-compatible: manual `compress()` calls still work

## Non-goals

- Changing compression strategies (sliding window, selective, deletion)
- Modifying tool schemas or token tracking
- Adding new configuration options

## Proposed Behavior (User-Facing)

- CLI / UX changes: None. The spinner message changes from "Compressing memory..." (in a separate call) to the same message (inline in the react loop). Functionally identical.
- Config changes: None.
- Output / logging changes: Debug log now says "Memory compressed (cache-safe)" instead of the old path. Token usage logs should show `cache_read_tokens > 0` for compaction calls.

## Invariants (Must Not Regress)

- Tool pair preservation (tool_use + tool_result stay together through compression)
- System message persistence across compressions
- Todo context injection into compression summaries
- Token tracking and compression metrics accuracy
- Manual `compress()` calls (backward compat)

## Design Sketch (Minimal)

### Before (old path)

```
add_message() → _should_compress() → compress() → compressor.compress()
                                                    └─ LLM call (bare prompt, no cache)
```

### After (cache-safe fork)

```
add_message() → _should_compress() → set _compression_needed = True

_react_loop():
  while True:
    if memory.needs_compression():
      context = memory.get_context_for_llm()      # system + messages (same as normal)
      context.append(memory.get_compaction_prompt()) # short instruction only
      response = _call_llm(context, tools=tools)   # cache hit on prefix!
      memory.apply_compression(extract_text(response), response.usage)
      continue  # re-enter loop with compressed context

    # normal flow...
```

The key insight: since the compaction call goes through `_call_llm()` with the same `tools` and the same message prefix, Anthropic's cache sees a prefix match and charges only 0.1× for the cached portion.

### New compressor methods

- `build_compaction_prompt(messages, strategy, target_tokens, todo_context) → str`: Returns a short instruction (~100 tokens) that does NOT include the messages themselves (they're already in the context).
- `apply_summary(messages, summary_text, strategy, todo_context) → CompressedMemory`: Takes the LLM's summary and wraps it into the correct message structure with metrics.

### New manager methods

- `needs_compression() → bool`: Checks the deferred flag.
- `get_compaction_prompt() → LLMMessage`: Builds the compaction instruction as a user message.
- `apply_compression(summary_text, usage) → None`: Applies the summary to memory state.

## Alternatives Considered

- **Option A: Duplicate the prefix in the compressor call** — Manually construct the same system prompt + tools in the compressor's LLM call. Fragile, duplicates logic, and the tools list isn't available in the compressor.
- **Option B (chosen): Do the compaction in _react_loop()** — The loop already has the full prefix. Simply add a compaction turn before the normal turn. Clean, no duplication, automatic cache reuse.
- **Option C: Pass tools/system to compressor** — Thread the tools and system messages through to the compressor. More invasive, still requires coordinating prefix order.

## Files Changed

| File | Change |
|------|--------|
| `agent/base.py` | Add compaction turn at top of `_react_loop()` |
| `memory/compressor.py` | Add `build_compaction_prompt()`, `apply_summary()`; keep existing `compress()` for backward compat |
| `memory/manager.py` | `add_message()` defers compression; add `needs_compression()`, `get_compaction_prompt()`, `apply_compression()`; `compress()` and `reset()` clear flag |
| `test/memory/test_compressor.py` | +10 tests for `build_compaction_prompt()` and `apply_summary()` |
| `test/memory/test_integration.py` | Updated 4 tests for deferred compression |
| `test/memory/test_memory_manager.py` | Updated 2 tests + 9 new tests for deferred compression API |

## Test Plan

- Unit tests: `./scripts/dev.sh test -q test/memory/` — 192 passed (was 173, +19 new)
- Full suite: `./scripts/dev.sh test -q` — 437 passed, 1 skipped
- Typecheck: `TYPECHECK_STRICT=1 ./scripts/dev.sh typecheck` — no issues
- Smoke run: Real cache hit verification requires live API calls with `DEBUG` logging to confirm `cache_read_tokens > 0` on compaction calls.

## Rollout / Migration

- Backward compatibility: Fully backward-compatible. `compress()` still works for manual calls. No config changes. No serialization format changes.
- Migration steps: None required.

## Risks & Mitigations

- **Compaction response may include tool calls**: The LLM is called with `tools=tools` for cache prefix matching, so it *could* attempt tool calls instead of summarizing. Mitigated by the compaction prompt being explicit ("Summarize the conversation above..."). In practice, models follow the instruction. If this becomes an issue, we could strip tool calls from the response.
- **Infinite compression loop**: If `apply_compression()` doesn't reduce tokens below threshold, `needs_compression()` could remain True. Mitigated by: (1) compression always reduces tokens significantly, (2) the flag is cleared in `apply_compression()` regardless of outcome, (3) `compress()` also clears the flag.
- **Deferred compression timing**: Messages added between the flag being set and the next `_react_loop()` iteration accumulate without compression. This is fine — the loop runs immediately after `add_message()` returns in normal flow.

## Open Questions

- None — implemented and tested.
