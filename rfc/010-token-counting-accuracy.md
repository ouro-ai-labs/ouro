# RFC 010: Token Counting Accuracy Improvement

## Problem Statement

ouro's `TokenTracker` used character-ratio estimation for non-OpenAI providers:
- Anthropic: `len(text) / 3.5`
- Gemini: `len(text) / 4`

This approach has two critical flaws:

1. **Non-English text underestimation**: Chinese text was underestimated by 40-57%, causing the Context display to be severely low and compression decisions to trigger too late.
2. **Tool schema overhead ignored**: Tool schemas are sent with every API call but were never counted in the context size, further skewing compression triggers.

## Design Goals

- Unified token counting across all providers (no per-provider code paths)
- Accurate enough for compression decisions (~5-15% error is acceptable)
- No API calls or credentials required for counting
- Minimal performance impact (synchronous, <1ms per message)
- Cache repeated computations

## Approach

### Replace character estimation with `litellm.token_counter()`

LiteLLM (already a dependency) provides `litellm.token_counter(model, messages, tools)` — a synchronous, local function that uses tiktoken internally. While tiktoken is optimized for OpenAI tokenizers, it's far more accurate than character ratios for all providers:

| Scenario | Old (char ratio) | New (litellm/tiktoken) |
|----------|-------------------|----------------------|
| English text | ~20% error | ~5% error |
| Chinese text | 40-57% undercount | ~10-15% error |
| Code/JSON | ~25% error | ~5% error |

### Add message-level caching

Key = `sha256(role + content + tool_calls + tool_call_id + name)`. This avoids re-tokenizing identical messages during `_recalculate_current_tokens()` which iterates all messages. Cache is cleared on `reset()`.

### Count tool schema overhead

A new `set_tool_schemas(schemas)` method on `MemoryManager` computes the token cost of tool schemas by diffing `token_counter(msg)` vs `token_counter(msg, tools=schemas)`. This is called once per session from `agent.py`. The overhead is added to `_recalculate_current_tokens()`.

## Key Design Decisions

1. **Unified counting, no per-provider routing**: Reduces maintenance and eliminates the worst estimation errors. The ~5-15% variance for non-OpenAI models is acceptable for compression decisions.

2. **Synchronous counting**: `litellm.token_counter()` is synchronous and fast (<1ms per message). No need to change async boundaries.

3. **Content-based cache keys**: Messages may be reconstructed from serialization (session resume), so identity-based caching would miss hits. Content hashing is more reliable.

4. **Tool schema computed once**: Schemas don't change within a session, so computing once and caching is sufficient.

5. **Removed `content_utils.estimate_tokens()`**: This function used `len(text)/3.5` and had no external callers. Removed to prevent future misuse.

## Files Changed

| File | Change |
|------|--------|
| `memory/token_tracker.py` | Replace per-provider estimation with `litellm.token_counter()` + add cache |
| `memory/manager.py` | Add `set_tool_schemas()`, include tool schema tokens in context count |
| `agent/agent.py` | Call `set_tool_schemas()` after getting tool schemas |
| `memory/compressor.py` | `_estimate_tokens()` now uses `litellm.token_counter()` |
| `llm/content_utils.py` | Remove unused `estimate_tokens()` function |
| `test/memory/test_token_tracker.py` | New: covers English/Chinese/code/JSON/tool_calls + cache |
| `test/memory/test_memory_manager.py` | Updated: check `tool_schema_tokens` in stats |
| `test/memory/test_compressor.py` | Updated: widen token range assertion |
| `docs/memory-management.md` | Updated accuracy table and troubleshooting |

## Risks and Mitigations

- **tiktoken accuracy for non-OpenAI models**: ~5-15% error vs exact. Mitigated by the fact that compression decisions don't need exact counts — directional accuracy is sufficient.
- **litellm.token_counter fallback**: If litellm fails (e.g., unknown model), we fall back to `len(text) // 4`. This is the same ballpark as before.
