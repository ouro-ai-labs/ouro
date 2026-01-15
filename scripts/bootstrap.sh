#!/bin/bash
set -euo pipefail

usage() {
  cat <<'EOF'
Bootstrap a local dev environment for AgenticLoop.

Creates/uses `.venv`, installs `.[dev]`, and initializes `.env` (if missing).

Usage:
  ./scripts/bootstrap.sh [--no-env] [--no-dev]

Options:
  --no-env   Do not create `.env` from `.env.example`
  --no-dev   Install without dev extras (installs `-e .` instead of `-e ".[dev]"`)
EOF
}

INIT_ENV="true"
WITH_DEV="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-env)
      INIT_ENV="false"
      shift
      ;;
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
  uv venv .venv
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

if [[ "$INIT_ENV" == "true" ]]; then
  if [[ ! -f ".env" ]] && [[ -f ".env.example" ]]; then
    echo "🧩 Initializing .env from .env.example ..."
    cp .env.example .env
  fi
fi

echo ""
echo "✅ Bootstrap complete"
echo ""
echo "Next:"
echo "  source .venv/bin/activate"
echo "  ./scripts/dev.sh test -q"
echo "  python main.py --task \"Calculate 1+1\""
