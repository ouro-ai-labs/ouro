# RFC 012: Sub-Agent Artifacts and Confidence-Guided Retrieval for `multi_task`

- Status: Proposed
- Authors: Li0k, Codex
- Date: 2026-02-19

## Summary

Improve `multi_task` context propagation by combining structured sub-agent summaries with optional markdown artifacts. Downstream tasks should consume compact summaries by default and fetch full artifact content only when confidence is low or conflicts/errors are detected.

## Problem

Current dependency context handling has improved from prefix truncation, but it still relies on a single in-memory text path. For long sub-agent outputs, the system needs both:
- compact, reliable context for downstream execution;
- full-fidelity output for audit/debug/follow-up.

A concrete failure mode is when key evidence is present in full output but absent in a compact dependency summary, and downstream tasks need that evidence to proceed safely.

## Goals

- Preserve `multi_task` as a simple LLM-first orchestration tool.
- Keep downstream context compact by default.
- Preserve full sub-agent output as per-task artifacts (`.md`) for on-demand retrieval.
- Add deterministic retrieval guidance so downstream/main-agent decisions are more consistent.
- Keep behavior backward compatible for existing `multi_task` callers.

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
  - Add optional `multi_task` argument: `artifact_dir` (default internal run directory).
- Output / logging changes:
  - Each task result contains: `summary`, `key_findings`, `errors`, `confidence`, and `artifact_path`.
  - Dependency context passed to downstream subtasks contains compact fields and a retrieval hint:
    - `RETRIEVAL_HINT: MUST_FETCH | SHOULD_FETCH | OPTIONAL`.

## Invariants (Must Not Regress)

- Non-`multi_task` execution paths remain unchanged.
- Dependency gating remains strict (`success` only).
- Default `max_parallel` remains `4` unless explicitly overridden.
- Missing artifacts must not fail the whole run; execution continues with fallback context.

## Design Sketch (Minimal)

1. Extend `TaskExecutionResult` with:
   - `confidence: float`
   - `artifact_path: str`
   - `retrieval_hint: str`
2. Keep current structured sub-agent response contract (`SUMMARY`, `KEY_FINDINGS`, `ERRORS`) and add `CONFIDENCE`.
3. Compute final confidence via lightweight hybrid rule:
   - deterministic base score with penalties (missing summary, fallback used, errors present, low findings quality, failed/skipped deps),
   - optional blend with parsed LLM self-confidence if present.
4. Write task artifact markdown:
   - path: `<artifact_dir>/<run_id>/task_<idx>.md`
   - content: task metadata + structured fields + raw output.
5. Build downstream dependency context as:
   - `SUMMARY`
   - `CONFIDENCE`
   - `ARTIFACT_PATH`
   - `RETRIEVAL_HINT`
   - (no full raw output by default)
6. Retrieval hint policy:
   - `MUST_FETCH`: confidence < 0.60, or meaningful errors, or missing summary
   - `SHOULD_FETCH`: 0.60 <= confidence < 0.80
   - `OPTIONAL`: confidence >= 0.80

## Alternatives Considered

- Option A: Keep compact summary only (no artifact path).
  - Simpler, but loses full-fidelity traceability.
- Option B: Always pass full raw output in dependency context.
  - Better recall, but worse latency/cost and context bloat.
- Option C: Prompt-only confidence (no local deterministic scoring).
  - Simpler, but less stable and harder to test.

## Test Plan

- Unit tests:
  - Parse `CONFIDENCE` and structured sections.
  - Confidence scoring and hint classification.
  - Artifact writing success/failure behavior.
- Targeted tests to run locally:
  - `./scripts/dev.sh test -q test/test_multi_task.py`
  - `./scripts/dev.sh test -q test/test_parallel_tools.py`
- Smoke run (one real CLI run):
  - `python main.py --task "Analyze flight options then produce dependent trip plan using multi_task" --verify`

## Rollout / Migration

- Backward compatibility:
  - Existing `multi_task(tasks, dependencies, max_parallel)` calls continue to work.
  - `artifact_dir` is optional.
- Migration steps (if any):
  - None required for existing users.
  - Docs update in README/examples after behavior lands.

## Risks & Mitigations

- Risk: Artifact file growth over time.
  - Mitigation: keep artifacts under run-scoped directory; add cleanup strategy in follow-up.
- Risk: Confidence miscalibration causes extra/insufficient retrieval.
  - Mitigation: deterministic base scoring + conservative thresholds + test coverage.
- Risk: Model output format drift.
  - Mitigation: local parser + fallback path already in place.

## Open Questions

- Should `artifact_dir` default to project-local (e.g. `.ouro_artifacts`) or runtime home dir?
- Should we add a lightweight cleanup command/retention policy in the same RFC or defer?
- Should `RETRIEVAL_HINT` be advisory only, or optionally enforced by a hard gate in `multi_task`?
