# RFC 006 — Ralph Loop (Outer Verification Loop)

**Status:** Implemented
**Created:** 2026-01-30
**Author:** —

## Abstract

Add an outer verification loop ("Ralph Loop") that checks whether the inner ReAct loop's final answer truly satisfies the original task. If the verifier deems the answer incomplete, feedback is injected and the inner loop re-enters. This provides an automated quality gate without changing the core ReAct loop.

## Problem Statement

Task completion in AgenticLoop is entirely LLM-driven: the inner ReAct loop terminates when the model emits `StopReason.STOP`. This means the model alone decides when it is "done," with no independent check that the answer is correct or complete. For complex tasks the model may stop prematurely — producing a partial answer, missing a subtask, or satisfying a surface reading of the prompt while missing deeper intent.

An outer loop that independently verifies completion and injects corrective feedback addresses this gap without adding complexity to the inner loop itself.

## Design Goals

1. **Non-invasive** — the inner `_react_loop` remains unchanged.
2. **Opt-in** — disabled by default (`RALPH_LOOP_ENABLED=false`). Existing behavior is untouched.
3. **Pluggable verification** — ships with an LLM-based verifier but accepts any object matching the `Verifier` Protocol.
4. **Bounded** — a configurable iteration cap (`RALPH_LOOP_MAX_ITERATIONS`, default 3) prevents runaway loops. On the final iteration, verification is skipped.
5. **Minimal token overhead** — the verification call uses no tools, a short system prompt, and a 512-token cap.

## Architecture

```
_ralph_loop (outer)
  └─ for iteration in 1..max_iterations:
       1. _react_loop()  →  result
       2. if last iteration  →  return result
       3. verifier.verify(task, result)
          ├─ complete  →  return result
          └─ incomplete  →  inject feedback as user message, continue
```

### Verification Interface

- `VerificationResult` dataclass: `complete: bool`, `reason: str`
- `Verifier` runtime-checkable Protocol: `async def verify(task, result, iteration, previous_results) -> VerificationResult`
- `LLMVerifier`: default implementation — lightweight LLM call (no tools, max 512 tokens). Truncates the agent answer to 4 000 chars and includes previous attempt context.

### Feedback Injection

Works naturally with the existing memory system:

1. `_react_loop()` completes → assistant's final message is already in memory.
2. `_ralph_loop()` appends a `user` message containing the verifier's feedback.
3. The next `_react_loop()` invocation picks up the full context via `memory.get_context_for_llm()`.

No changes to the memory system are required.

### Configuration

Two new keys in `config.py` (and `.aloop/config` template):

| Key | Default | Description |
|---|---|---|
| `RALPH_LOOP_ENABLED` | `false` | Enable the outer verification loop |
| `RALPH_LOOP_MAX_ITERATIONS` | `3` | Maximum outer iterations before returning |

## Alternatives Considered

1. **Post-hoc tool call** — add a "verify" tool the agent can call itself. Rejected because the agent already decides when to stop; giving it a verify tool doesn't solve the "stops too early" problem.
2. **Prompt engineering only** — add "double-check your answer" instructions. Unreliable; the model may still skip verification.
3. **Always-on** — run verification unconditionally. Rejected for cost/latency reasons; opt-in is safer as a first step.

## Risks and Open Questions

- **Cost**: each outer iteration adds one verification LLM call plus a full re-run of the inner loop. The default cap of 3 bounds worst-case overhead.
- **Verifier quality**: the LLM verifier uses the same model. A weaker/faster model could be used in future for cost savings.
- **Feedback loop divergence**: the agent could oscillate if feedback is contradictory. The iteration cap mitigates this.

## Future Directions

- Support a separate (cheaper/faster) model for verification.
- Structured verification output (JSON) for richer feedback.
- Per-task opt-in via CLI flag (`--verify`).
