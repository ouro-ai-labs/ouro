#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run(*args: str) -> str:
    try:
        return subprocess.check_output(args, cwd=_repo_root(), text=True).strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Command failed: {' '.join(args)}") from e


def _try_run(*args: str) -> str | None:
    try:
        return subprocess.check_output(args, cwd=_repo_root(), text=True).strip()
    except subprocess.CalledProcessError:
        return None


def _default_base_ref() -> str:
    if _try_run("git", "rev-parse", "--verify", "origin/main") is not None:
        merge_base = _run("git", "merge-base", "HEAD", "origin/main")
        return merge_base
    return "HEAD~1"


def main(argv: list[str]) -> int:
    base = argv[1] if len(argv) > 1 else _default_base_ref()

    diff_stat = _run("git", "diff", "--stat", f"{base}..HEAD")
    changed_files = _run("git", "diff", "--name-only", f"{base}..HEAD")
    commits = _run("git", "log", "--oneline", f"{base}..HEAD")

    root = _repo_root()
    template_path = root / ".github" / "pull_request_template.md"
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else None

    if template:
        print(template.strip())
        print()
    else:
        print("## Summary")
        print()
        print("<what changed, why, and user-facing impact>")
        print()

        print("## Scope")
        print()
        print("- Goals:")
        print("- Non-goals:")
        print()

    print("## Change List")
    print()
    print("```")
    print(diff_stat or "(no diff)")
    print("```")
    print()

    print("## Changed Files")
    print()
    print("```")
    print(changed_files or "(none)")
    print("```")
    print()

    print("## Commits")
    print()
    print("```")
    print(commits or "(none)")
    print("```")
    print()

    if not template:
        print("## Test Plan")
        print()
        print("- [ ] `./scripts/dev.sh invariants`")
        print("- [ ] `./scripts/dev.sh precommit`")
        print("- [ ] `TYPECHECK_STRICT=1 ./scripts/dev.sh typecheck`")
        print("- [ ] `./scripts/dev.sh test -q`")
        print("- [ ] Smoke: `python main.py --task \"<...>\" --verify` (or explain why not)")
        print()

    print("## Risks / Regressions Considered")
    print()
    print("- Invariants (must not regress):")
    print("- Edge cases / adversarial inputs:")
    print("- Backward compatibility / migration:")
    print()

    print("## Notes for Reviewers")
    print()
    print("- Where to start reviewing:")
    print("- Follow-up work (if any):")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
