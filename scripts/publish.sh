#!/bin/bash
# Publish the package to PyPI

set -e

echo "🚀 Publishing AgenticLoop to PyPI..."

source ./scripts/_env.sh

usage() {
    cat <<'EOF'
Usage:
  ./scripts/publish.sh [--repository <name>] [--test] [--yes]

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

if [[ -z "$REPOSITORY" ]]; then
    echo "❌ Missing value for --repository"
    usage
    exit 2
fi

# Check if dist/ exists
if [ ! -d "dist" ]; then
    echo "❌ No dist/ directory found. Run ./scripts/build.sh first."
    exit 1
fi

# Install twine if needed
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

# Upload
"$PYTHON" -m twine upload --repository "$REPOSITORY" dist/*

echo ""
echo "✅ Published!"
