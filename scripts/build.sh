#!/bin/bash
# Build the package for distribution

set -e  # Exit on error

echo "🔨 Building AgenticLoop package..."

source ./scripts/_env.sh

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build/ dist/ *.egg-info

# Install build tools
echo "Installing build tools..."
uv pip install --python "$PYTHON" --upgrade build twine

# Build the package
echo "Building package..."
"$PYTHON" -m build

echo "✅ Build complete! Distribution files are in dist/"
ls -lh dist/

echo ""
echo "Next steps:"
echo "  1. Test locally: pip install dist/agentic_loop-*.whl"
echo "  2. Upload to PyPI: twine upload dist/*"
