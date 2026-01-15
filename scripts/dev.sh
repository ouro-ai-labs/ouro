#!/bin/bash
set -euo pipefail

usage() {
  cat <<'EOF'
AgenticLoop dev workflow helper.

Usage:
  ./scripts/dev.sh <command> [args...]

Commands:
  install        Install editable with dev deps (requires .venv; use bootstrap for creation)
  test           Run pytest (passes args through)
  format         Run black + isort
  lint           Check formatting (black/isort)
  precommit      Run pre-commit on all files
  typecheck      Run mypy (best-effort; set TYPECHECK_STRICT=1 to fail)
  build          Build dist/ artifacts
  publish        Publish dist/ via twine (see scripts/publish.sh)

Examples:
  ./scripts/dev.sh install
  ./scripts/dev.sh test -q
  ./scripts/dev.sh format
  ./scripts/dev.sh lint
  ./scripts/dev.sh precommit
  ./scripts/dev.sh typecheck
  ./scripts/dev.sh build
  ./scripts/dev.sh publish --test
EOF
}

cmd="${1:-}"
if [[ -z "$cmd" ]] || [[ "$cmd" == "-h" ]] || [[ "$cmd" == "--help" ]]; then
  usage
  exit 0
fi
shift || true

case "$cmd" in
  install)
    source ./scripts/_env.sh
    uv pip install --python "$PYTHON" -e ".[dev]" "$@"
    ;;
  test)
    ./scripts/test.sh "$@"
    ;;
  format)
    ./scripts/format.sh "$@"
    ;;
  lint)
    ./scripts/lint.sh "$@"
    ;;
  precommit)
    ./scripts/precommit.sh "$@"
    ;;
  typecheck)
    ./scripts/typecheck.sh "$@"
    ;;
  build)
    ./scripts/build.sh "$@"
    ;;
  publish)
    ./scripts/publish.sh "$@"
    ;;
  *)
    echo "Unknown command: $cmd"
    usage
    exit 2
    ;;
esac
