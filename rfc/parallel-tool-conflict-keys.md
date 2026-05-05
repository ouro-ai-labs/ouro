# RFC: Parallel Tool Dispatch via Conflict Keys

- Status: Draft
- Authors: Yixin Luo
- Date: 2026-05-04

## Summary

Replace the loop's binary "all readonly → parallel, otherwise → sequential"
tool-dispatch rule with a finer-grained scheme based on per-call **conflict
keys**. Two tool calls in the same LLM turn can run in parallel whenever
their declared resource scopes are disjoint, instead of requiring every
call in the batch to be `readonly`.

## Problem

`Agent._dispatch_tools` (`ouro/core/loop/agent.py:180`) currently runs the
whole batch in parallel only if **every** tool in the batch has
`BaseTool.readonly = True`. As soon as one write-tool appears, the entire
batch falls back to sequential execution.

In practice the LLM often emits batches like:

- `read_file(A)` + `read_file(B)` + `write_file(C)` — all on different
  paths, but the write forces sequential.
- `write_file(A)` + `write_file(B)` — disjoint files, no actual conflict.

These run sequentially today even though there is no real shared resource.
The result is wall-clock latency proportional to the number of file edits
in a turn — visible in long edit-heavy tasks.

## Goals

- Allow non-readonly tool calls to execute in parallel when they touch
  disjoint resources.
- Preserve current behavior (sequential) for tools that don't declare a
  scope, so adoption is opt-in per tool.
- Keep ordering semantics: results are returned in the same order as the
  LLM's `tool_calls` list.
- Keep Bash/shell sequential by default — process/env/network side effects
  are out of scope for this RFC.

## Non-goals

- A general capability-effect type system. The scope is just "resource keys".
- Read/write key separation. We model each call with a single set of keys;
  any overlap is a conflict. (Possible future extension.)
- Bash command-line parsing to classify shell calls as readonly. Tracked
  separately.
- Reordering tool calls to maximize parallelism. We process calls in the
  order the LLM emitted them and only group adjacent compatible calls.

## Proposed Behavior (User-Facing)

No CLI/config change. Tool authors gain one optional override; the loop
just dispatches faster when tools opt in.

- Tool authors override `BaseTool.conflict_keys(**arguments)` to return the
  set of resource keys (e.g. absolute paths) the call would touch.
- Built-in opt-ins in this PR: `FileWriteTool` (returns `{abs(file_path)}`).
- All `readonly = True` tools stay parallel-safe (default key set is empty,
  i.e. no conflicts).
- All other tools default to "unknown scope" and remain sequential as today.

Example:

```text
LLM emits: [read_file(A), write_file(B), write_file(A), read_file(C)]

Batches built by the loop:
  Batch 1 (parallel): read_file(A), write_file(B)
  Batch 2 (alone):    write_file(A)        # conflicts with batch 1's read of A
  Batch 3 (alone):    read_file(C)         # readonly, runs alone in its own batch
                                             (batch 2's scope is {A}, disjoint
                                              from C's empty scope, so could merge —
                                              see Design Sketch)
```

## Invariants (Must Not Regress)

- [ ] Single-call batches still run via `_exec_sequential` (unchanged path).
- [ ] A batch where every call is `readonly` still runs fully in parallel.
- [ ] A batch containing any tool without an opt-in scope and without
      `readonly` runs fully sequentially (current default).
- [ ] `ToolResult` order matches the input `tool_calls` order.
- [ ] On exception inside a parallel batch, individual tool errors are
      surfaced as result strings (current `ToolExecutor` behavior).
- [ ] Shell tool stays sequential.

## Design Sketch (Minimal)

### 1. `BaseTool.conflict_keys`

```python
class BaseTool(ABC):
    readonly: bool = False

    def conflict_keys(self, **kwargs: Any) -> set[str] | None:
        """Resource keys this call would touch.

        - empty set: no conflicts (parallel-safe with anything).
        - non-empty: parallel-safe with calls whose key sets are disjoint.
        - None: unknown scope; the call must run in a batch by itself.

        Default: empty set if ``readonly`` else ``None``.
        """
        return set() if self.readonly else None
```

### 2. `ToolRegistry` protocol gains a method

```python
def conflict_keys(self, name: str, arguments: dict[str, Any]) -> set[str] | None: ...
```

`ToolExecutor` implements it by calling the tool's `conflict_keys`.
`is_tool_readonly` is retained (backward compat, narrow purpose).

### 3. Dispatcher: prefix-greedy batching

`_dispatch_tools` walks the `tool_calls` list once, building batches:

- Start a new batch with the first call. Track the union of its keys.
- For each subsequent call:
  - If its keys are `None` → flush current batch, run it alone next.
  - Else if its keys intersect the current batch's union → flush, start new
    batch from this call.
  - Else → append to current batch, union keys.
- Each batch with `len > 1` runs via `_exec_parallel`; `len == 1` runs via
  `_exec_sequential`.

This preserves emit order and never reorders calls across a conflict.

### 4. Built-in opt-ins (this PR)

- `FileWriteTool` → `{os.path.abspath(file_path)}`
- (Future PRs can add `SmartEditTool`, `EditTool` if it lands, etc.)

## Alternatives Considered

- **Read/write key separation.** More precise (write+read of same path is
  a conflict, two reads aren't). Rejected for v1 — readonly tools already
  return empty set, so the only thing we lose is "two writes to the same
  path can't merge", which is fine: they shouldn't merge.
- **Per-tool capability/effect type.** Too much surface area; we don't
  have other consumers of effect metadata.
- **Reorder calls to maximize parallelism.** Risks changing observable
  semantics; the LLM's emit order is its planning order.

## Test Plan

- Unit tests in `test/test_parallel_tools.py`:
  - `BaseTool.conflict_keys` defaults: readonly → `set()`, non-readonly → `None`.
  - `FileWriteTool.conflict_keys({"file_path": "/abs/x"})` → `{"/abs/x"}`.
  - Dispatcher batching cases:
    - all readonly → one parallel batch.
    - readonly + scoped writes to disjoint paths → one parallel batch.
    - two writes to same path → two sequential batches.
    - any unknown-scope tool → that call runs alone, neighbors batch around it.
    - order of `ToolResult` preserved.
  - Existing parallel-execution timing test still passes.
- Targeted: `./scripts/dev.sh test -q test/test_parallel_tools.py`.
- Smoke: `python main.py --task "edit two unrelated files"` and observe a
  single parallel batch in the spinner label.

## Rollout / Migration

- Backward compatible. Existing `BaseTool` subclasses inherit the default
  `conflict_keys`, which preserves current sequential behavior for
  non-readonly tools. Existing `readonly = True` tools keep batching as
  before.
- Tools opt in incrementally by overriding `conflict_keys`.

## Risks & Mitigations

- **False-disjoint claims.** A tool returns `{"a"}` but actually also
  writes `/b`. → Tools opt in deliberately; review at the tool boundary.
- **Path-normalization pitfalls.** `./x` vs `/abs/x` look disjoint but
  aren't. → Tools that opt in must `os.path.abspath` their keys; document
  this in the docstring and in `tools/CLAUDE.md`.
- **Shell still serialized.** Acceptable for v1; revisit when a
  command-allowlist is in place.

## Open Questions

- Should `conflict_keys = set()` (the readonly default) be allowed to
  merge with a single non-`None` writer? Currently yes — readonly's empty
  set has no intersection, so it joins any batch. This is intended.
- Future: do we want a `read_keys` / `write_keys` split for the case where
  two readers of the same path want to be parallel with a writer of a
  different path mid-batch? Defer.
