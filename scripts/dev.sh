#!/bin/bash
set -euo pipefail

usage() {
  cat <<'EOF'
ouro dev workflow helper.

Usage:
  ./scripts/dev.sh <command> [args...]

Commands:
  install        Install editable with dev deps (requires .venv; use bootstrap for creation)
  test           Run pytest (passes args through)
  format         Run black + isort + ruff --fix
  lint           Check formatting/lint (black/isort/ruff)
  precommit      Run pre-commit on all files
  typecheck      Run mypy (best-effort; set TYPECHECK_STRICT=1 to fail)
  check          Run precommit + typecheck + tests
  build          Build dist/ artifacts
  publish        Publish dist/ via twine

Examples:
  ./scripts/dev.sh install
  ./scripts/dev.sh test -q
  ./scripts/dev.sh format
  ./scripts/dev.sh lint
  ./scripts/dev.sh precommit
  ./scripts/dev.sh typecheck
  ./scripts/dev.sh check
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
    source ./scripts/_env.sh
    "$PYTHON" -m pytest test/ "$@"
    ;;
  format)
    source ./scripts/_env.sh
    "$PYTHON" -m black .
    "$PYTHON" -m isort .
    "$PYTHON" -m ruff check --fix .
    ;;
  lint)
    source ./scripts/_env.sh
    "$PYTHON" -m black --check .
    "$PYTHON" -m isort --check-only .
    "$PYTHON" -m ruff check .
    ;;
  precommit)
    source ./scripts/_env.sh
    "$PYTHON" -m pre_commit run --all-files "$@"
    ;;
  typecheck)
    STRICT="${TYPECHECK_STRICT:-0}"

    source ./scripts/_env.sh

    set +e
    "$PYTHON" -m mypy \
      agent llm memory tools utils main.py config.py
    status=$?
    set -e

    if [[ "$status" -ne 0 ]] && [[ "$STRICT" == "1" ]]; then
      exit "$status"
    fi

    exit 0
    ;;
  check)
    ./scripts/dev.sh precommit
    ./scripts/dev.sh typecheck
    ./scripts/dev.sh test
    ;;
  build)
    source ./scripts/_env.sh

    echo "🔨 Building ouro package..."

    echo "Cleaning previous builds..."
    rm -rf build/ dist/ *.egg-info

    echo "Installing build tools..."
    uv pip install --python "$PYTHON" --upgrade build twine

    echo "Building package..."
    "$PYTHON" -m build

    echo "✅ Build complete! Distribution files are in dist/"
    ls -lh dist/

    echo ""
    echo "Next steps:"
    echo "  1. Test locally: pip install dist/ouro_ai-*.whl"
    echo "  2. Upload to PyPI: twine upload dist/*"
    ;;
  publish)
    source ./scripts/_env.sh

    usage_publish() {
      cat <<'EOF'
Usage:
  ./scripts/dev.sh publish [--repository <name>] [--test] [--yes]

Options:
  --repository <name>  Twine repository (default: pypi)
  --test               Shortcut for --repository testpypi
  --yes                Skip confirmation prompt (dangerous)
EOF
    }

    REPOSITORY="pypi"
    YES="false"

    while [[ $# -gt 0 ]]; do
      case "$1" in
        --repository)
          REPOSITORY="${2:-}"
          shift 2
          ;;
        --test)
          REPOSITORY="testpypi"
          shift
          ;;
        --yes)
          YES="true"
          shift
          ;;
        -h|--help)
          usage_publish
          exit 0
          ;;
        *)
          echo "Unknown argument: $1"
          usage_publish
          exit 2
          ;;
      esac
    done

    if [[ -z "$REPOSITORY" ]]; then
      echo "❌ Missing value for --repository"
      usage_publish
      exit 2
    fi

    if [[ ! -d "dist" ]]; then
      echo "❌ No dist/ directory found. Run ./scripts/dev.sh build first."
      exit 1
    fi

    uv pip install --python "$PYTHON" --upgrade twine

    echo ""
    echo "⚠️  This will upload to repository: $REPOSITORY"
    echo "Dist files:"
    ls -lh dist/ || true

    if [[ "$YES" != "true" ]]; then
      if [[ -t 0 ]]; then
        read -p "Continue? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
          echo "Cancelled."
          exit 1
        fi
      else
        echo "❌ Refusing to publish without a TTY. Re-run with --yes if you really mean it."
        exit 1
      fi
    fi

    "$PYTHON" -m twine upload --repository "$REPOSITORY" dist/*

    echo ""
    echo "✅ Published!"
    ;;
  *)
    echo "Unknown command: $cmd"
    usage
    exit 2
    ;;
esac
