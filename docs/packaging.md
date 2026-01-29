# Packaging and Distribution Guide

This guide explains how to package and distribute AgenticLoop.

## 📦 Quick Start - Local Installation

### Install for Development

Prerequisites: Python 3.12+ and `uv` (https://github.com/astral-sh/uv).

```bash
# Bootstrap dev environment (creates .venv, installs deps)
./scripts/bootstrap.sh
```

Note: development workflow requires `uv` (https://github.com/astral-sh/uv).

Now you can use it (after activating `.venv` or via `./.venv/bin/aloop`):
```bash
aloop --help
aloop
```

## 🚀 Publishing to PyPI

### 1. Build the Package

```bash
./scripts/dev.sh build
```

This creates distribution files in `dist/`:
- `agentic_loop-0.1.0-py3-none-any.whl` (wheel)
- `agentic_loop-0.1.0.tar.gz` (source distribution)

### 2. Test Locally

```bash
# Install from wheel
pip install dist/agentic_loop-0.1.0-py3-none-any.whl

# Test it
aloop
```

### 3. Publish to Test PyPI (Recommended First)

```bash
# Create account at https://test.pypi.org/
# Get API token from account settings

# Upload to test PyPI
./scripts/dev.sh publish --test

# Install from test PyPI
pip install --index-url https://test.pypi.org/simple/ AgenticLoop
```

### 4. Publish to Production PyPI

```bash
# Create account at https://pypi.org/
# Get API token

# Upload
./scripts/dev.sh publish

# Now anyone can install
pip install AgenticLoop
```

## 🐳 Docker Distribution

### Build Docker Image

```bash
docker build -t AgenticLoop:latest .
```

### Run with Docker

```bash
# Interactive mode
docker run -it --rm \
  -e ANTHROPIC_API_KEY=your_key \
  -v $(pwd)/data:/app/data \
  AgenticLoop --mode react

# Single task
docker run --rm \
  -e ANTHROPIC_API_KEY=your_key \
  AgenticLoop --mode react --task "Analyze this code"
```

### Publish Docker Image

```bash
# Tag for Docker Hub
docker tag AgenticLoop:latest yourusername/AgenticLoop:0.1.0
docker tag AgenticLoop:latest yourusername/AgenticLoop:latest

# Push
docker push yourusername/AgenticLoop:0.1.0
docker push yourusername/AgenticLoop:latest
```

## 📱 Standalone Executable (Optional)

For users without Python, create a standalone executable:

### Using PyInstaller

```bash
# Install PyInstaller
pip install pyinstaller

# Create executable
pyinstaller --onefile \
  --name AgenticLoop \
  --add-data "config.py:." \
  --hidden-import anthropic \
  --hidden-import openai \
  --hidden-import google.genai \
  main.py

# Executable will be in dist/AgenticLoop
```

**Note**: The executable will be ~50-100MB and platform-specific.

## 📋 Release Checklist

Before publishing a new version:

- [ ] Update version in `pyproject.toml`
- [ ] Update CHANGELOG.md
- [ ] Format: `./scripts/dev.sh format`
- [ ] Run tests: `pytest`
- [ ] Build package: `./scripts/dev.sh build`
- [ ] Test locally: `pip install dist/*.whl`
- [ ] Create git tag: `git tag v0.1.0 && git push --tags`
- [ ] Publish to PyPI: `./scripts/dev.sh publish`
- [ ] Create GitHub release with changelog

## 🔧 Troubleshooting

### Import Errors After Installation

If you get import errors, make sure all packages are included in `pyproject.toml`:
```toml
[tool.setuptools]
packages = ["agent", "llm", "memory", "tools", "utils"]
```

### Missing Files

Add them to `MANIFEST.in`:
```
include important_file.txt
recursive-include data *.json
```

### Version Conflicts

Use constraints file:
```bash
pip install AgenticLoop -c constraints.txt
```

## 📚 Distribution Methods Summary

| Method | Command | Use Case |
|--------|---------|----------|
| **Local Dev** | `./scripts/bootstrap.sh` | Development, testing |
| **PyPI** | `pip install AgenticLoop` | Public distribution |
| **Docker** | `docker run AgenticLoop --mode react --task "..."` | Containerized deployment |
| **Executable** | `./AgenticLoop` | Non-Python users |
| **GitHub** | `pip install git+https://github.com/user/repo` | Direct from source |

## 🎯 Recommended Workflow

1. **Development**: Use `./scripts/bootstrap.sh`
2. **Testing**: Build and test with `./scripts/dev.sh build`
3. **Distribution**: Publish to PyPI
4. **Users**: Install with `pip install AgenticLoop`
