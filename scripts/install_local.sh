#!/bin/bash
# Install the package locally for development/testing

set -e

echo "📦 Installing AgenticLoop locally..."

# Install in editable mode with dependencies
python3 -m pip install -e .

echo ""
echo "✅ Installation complete!"
echo ""
echo "Try it out:"
echo "  aloop --help"
echo "  aloop interactive"
echo ""
echo "Or import in Python:"
echo "  from agent.react_agent import ReActAgent"
