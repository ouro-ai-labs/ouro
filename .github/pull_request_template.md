## Summary

What changed and why (user-facing when applicable).

## Scope

- Goals:
- Non-goals:

## Invariants (Must Not Regress)

- [ ] List 3–5 existing behaviors that must stay the same

## Acceptance Criteria

- [ ] Concrete, testable outcomes

## Test Plan

- [ ] Targeted tests:
- [ ] `./scripts/dev.sh test -q`
- [ ] `TYPECHECK_STRICT=1 ./scripts/dev.sh typecheck`

## Smoke Run (Real CLI)

- [ ] `python main.py --task "<...>" --verify` (or explain why not)

## Adversarial Review (Answer Briefly)

- What existing behavior could this break? (3–5 invariants)
- Worst-case input/output size? Any truncation/limits?
- Any secrets/logging risks?
- Any async/blocking I/O added on hot paths?
- What error message does the user see on failure? Is it actionable?

## Docs / Compatibility

- [ ] Updated relevant docs (`README.md`, `docs/examples.md`, `docs/configuration.md`) when needed
- [ ] No secrets committed; no generated artifacts (`.venv/`, `dist/`, `build/`, `*.egg-info/`)

---

Note: This template is also embedded in `CLAUDE.md` so coding-agents always see it.
