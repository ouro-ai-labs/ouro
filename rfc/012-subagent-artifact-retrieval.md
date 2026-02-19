# RFC 012: Sub-Agent Artifacts and Required-Fetch Hints for `multi_task`

- Status: Proposed
- Authors: Li0k, Codex
- Date: 2026-02-19

## Summary

Improve `multi_task` context propagation by combining structured sub-agent summaries with optional markdown artifacts. Downstream tasks should consume compact summaries by default and must fetch full artifact content when the sub-agent response does not conform to the required output template.

## Problem

Current dependency context handling has improved from prefix truncation, but it still relies on a single in-memory text path. For long sub-agent outputs, the system needs both:
- compact, reliable context for downstream execution;
- full-fidelity output for audit/debug/follow-up.

A concrete failure mode is when key evidence is present in full output but absent in a compact dependency summary, and downstream tasks need that evidence to proceed safely. Another failure mode is malformed sub-agent output that does not follow the required template, making the compact context unreliable.

## Goals

- Preserve `multi_task` as a simple LLM-first orchestration tool.
- Keep downstream context compact by default.
- Preserve full sub-agent output as per-task artifacts (`.md`) for on-demand retrieval.
- Add a deterministic, minimal fetch hint based on template conformance.
- Keep the policy simple enough to avoid a scoring engine.

## Non-goals

- Introduce a new global workflow engine or heavy DAG runtime.
- Replace existing ReAct loop architecture.
- Add distributed workers or persistent artifact indexing.
- Force all downstream steps to read artifacts.

## Proposed Behavior (User-Facing)

Describe the observable behavior.

- CLI / UX changes:
  - No new top-level CLI command.
  - `multi_task` outputs include artifact path metadata per task when available.
- Config changes:
  - No global config required in v1.
  - Add optional `multi_task` argument: `artifact_dir` (default local project path).
  - Default artifact root: `<cwd>/.ouro_artifacts/<run_id>/`.
- Output / logging changes:
  - Each task result contains: `summary`, `key_findings`, `errors`, `artifact_path`, `fetch_hint`, and `template_conformant`.
  - Dependency context passed to downstream subtasks contains compact fields and a retrieval hint:
    - `FETCH_HINT: NONE | REQUIRED`.
    - When output is non-conformant, include a small best-effort `NON_CONFORMANT_CONTEXT` preview.
  - No raw-output truncation fallback is included in dependency context.

## Invariants (Must Not Regress)

- Non-`multi_task` execution paths remain unchanged.
- Dependency gating remains strict (`success` only).
- Default `max_parallel` remains `4` unless explicitly overridden.
- Missing artifacts must not fail the whole run; execution continues with summary-first context.
- Downstream tasks must not receive empty dependency context; at least one text signal is always passed (`SUMMARY` or `NON_CONFORMANT_CONTEXT`).

## Design Sketch (Minimal)

1. Extend `TaskExecutionResult` with:
   - `artifact_path: str`
   - `fetch_hint: str`
   - `template_conformant: bool`
2. Keep current structured sub-agent response contract (`SUMMARY`, `KEY_FINDINGS`, `ERRORS`).
3. Parse structured sections and evaluate template conformance:
   - Expected sections: `SUMMARY`, `KEY_FINDINGS`, `ERRORS`
   - `template_conformant=true` only when all expected sections are parsed successfully
4. Compute fetch hint with a strict minimal rule:
   - `FETCH_HINT=REQUIRED` when `template_conformant=false`
   - otherwise `FETCH_HINT=NONE`
5. Write task artifact markdown:
   - path: `<cwd>/.ouro_artifacts/<run_id>/task_<idx>.md` by default, or `<artifact_dir>/<run_id>/task_<idx>.md` when provided
   - content: task metadata + structured fields + raw output.
6. Build downstream dependency context as:
   - `SUMMARY` (when `template_conformant=true`)
   - `NON_CONFORMANT_CONTEXT` (when `template_conformant=false`, best-effort preview from raw output)
   - `ARTIFACT_PATH`
   - `FETCH_HINT`
   - `TEMPLATE_CONFORMANT`
   - (no full raw output and no char-truncated fallback)
7. `FETCH_HINT=REQUIRED` is a hard runtime rule when `ARTIFACT_PATH` is available:
   - orchestrator injects artifact content before dependent subtask execution.
8. If `FETCH_HINT=REQUIRED` but artifact is unavailable:
   - do not fail the whole run;
   - continue with `NON_CONFORMANT_CONTEXT` and explicit `ARTIFACT_PATH=UNAVAILABLE`.

## Alternatives Considered

- Option A: Keep compact summary only (no artifact path).
  - Simpler, but loses full-fidelity traceability.
- Option B: Always pass full raw output in dependency context.
  - Better recall, but worse latency/cost and context bloat.
- Option C: Confidence-scored retrieval hints.
  - More flexible, but over-engineered for v1 and harder to tune.

## Test Plan

- Unit tests:
  - Parse structured sections and classify `template_conformant`.
  - `FETCH_HINT` classification (`NONE` vs `REQUIRED`).
  - Dependency context generation has no raw-output truncation fallback and preserves a non-empty signal.
  - When `FETCH_HINT=REQUIRED` and artifact exists, orchestrator fetch is mandatory before downstream execution.
  - When `FETCH_HINT=REQUIRED` and artifact is unavailable, fallback path uses `NON_CONFORMANT_CONTEXT`.
  - Artifact writing success/failure behavior.
- Targeted tests to run locally:
  - `./scripts/dev.sh test -q test/test_multi_task.py`
  - `./scripts/dev.sh test -q test/test_parallel_tools.py`
- Smoke run (one real CLI run):
  - `python main.py --task "Analyze flight options then produce dependent trip plan using multi_task" --verify`

## Rollout / Migration

- Backward compatibility:
  - Not guaranteed. This is a behavior-level breaking change for result formatting and retrieval metadata.
  - Existing automation/scripts parsing legacy free-form result text must be updated.
- Migration steps (if any):
  - Update downstream parsers/prompts to consume `summary/fetch_hint/template_conformant/artifact_path`.
  - Docs update in README/examples after behavior lands.

## Risks & Mitigations

- Risk: Artifact file growth over time.
  - Mitigation: keep artifacts under run-scoped directory; add cleanup strategy in follow-up.
- Risk: Template-conformance policy may trigger frequent retrieval if model format drifts.
  - Mitigation: keep prompt format explicit; ensure parser and tests cover common formatting variants.
- Risk: Mandatory retrieval can add latency on dependency-heavy chains.
  - Mitigation: enforce retrieval only for `REQUIRED`; keep conformant path summary-first.
- Risk: Model output format drift.
  - Mitigation: local parser + artifact retrieval path when non-conformant.

## Open Questions

- Should we add a lightweight cleanup command/retention policy in the same RFC or defer?
- Should we add a retry-once path for non-conformant sub-agent output before marking `FETCH_HINT=REQUIRED`?
