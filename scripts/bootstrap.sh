#!/bin/bash
set -euo pipefail

usage() {
  cat <<'EOF'
Bootstrap a local dev environment for ouro.

Creates/uses `.venv` and installs `.[dev]`.

Usage:
  ./scripts/bootstrap.sh [--no-dev]

Options:
  --no-dev   Install without dev extras (installs `-e .` instead of `-e ".[dev]"`)
EOF
}

WITH_DEV="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-dev)
      WITH_DEV="false"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 2
      ;;
  esac
done

if ! command -v uv >/dev/null 2>&1; then
  echo "❌ uv not found. Install uv (https://github.com/astral-sh/uv) first."
  exit 1
fi

if [[ ! -d ".venv" ]]; then
  echo "📦 Creating virtual environment in .venv ..."
  # Use Python 3.12.x to ensure compatibility with all dependencies
  # (tree-sitter-languages doesn't have wheels for Python 3.13+ yet)
  # Update the upper bound when dependencies add support for newer Python versions
  uv venv .venv --python ">=3.12,<3.13"
fi

VENV_PY=".venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "❌ .venv exists but $VENV_PY is not executable."
  exit 1
fi

echo "⬆️  Upgrading pip ..."
uv pip install --python "$VENV_PY" -U pip

echo "📦 Installing dependencies ..."
install_args=()
if [[ "$WITH_DEV" == "true" ]]; then
  install_args=(-e ".[dev]")
else
  install_args=(-e .)
fi

# Install into the venv explicitly.
uv pip install --python "$VENV_PY" "${install_args[@]}"

echo ""
echo "✅ Bootstrap complete"
echo ""
echo "Next:"
echo "  source .venv/bin/activate"
echo "  ./scripts/dev.sh test -q"
echo "  python main.py --task \"Calculate 1+1\""
