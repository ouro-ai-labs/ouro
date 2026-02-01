# Packaging and Distribution

## Local Development

Prerequisites: Python 3.12+ and [uv](https://github.com/astral-sh/uv).

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
aloop --help
```

## Building

```bash
./scripts/dev.sh build
```

Creates `dist/agentic_loop-*.whl` and `dist/agentic_loop-*.tar.gz`.

Test locally:
```bash
pip install dist/agentic_loop-*.whl
aloop --task "Calculate 1+1"
```

## Publishing to PyPI

### Test PyPI (recommended first)

```bash
./scripts/dev.sh publish --test
pip install --index-url https://test.pypi.org/simple/ AgenticLoop
```

### Production PyPI

```bash
./scripts/dev.sh publish
```

`publish` is interactive by default and refuses to run without a TTY unless you pass `--yes`.

## Docker

### Build

```bash
docker build -t agentic-loop:latest .
```

### Run

Mount `.aloop/` to provide model configuration:

```bash
# Interactive mode
docker run -it --rm \
  -v $(pwd)/.aloop:/app/.aloop \
  agentic-loop

# Single task
docker run --rm \
  -v $(pwd)/.aloop:/app/.aloop \
  agentic-loop --task "Calculate 1+1"
```

### Publish

```bash
docker tag agentic-loop:latest yourusername/agentic-loop:0.1.0
docker tag agentic-loop:latest yourusername/agentic-loop:latest
docker push yourusername/agentic-loop:0.1.0
docker push yourusername/agentic-loop:latest
```

## Release Checklist

1. Update version in `pyproject.toml`
2. Run checks: `./scripts/dev.sh check`
3. Build: `./scripts/dev.sh build`
4. Test locally: `pip install dist/*.whl && aloop --task "Calculate 1+1"`
5. Create git tag: `git tag v0.x.0 && git push --tags`
6. Publish: `./scripts/dev.sh publish`
7. Create GitHub release

## Distribution Summary

| Method | Command |
|--------|---------|
| Local dev | `./scripts/bootstrap.sh` |
| Docker | `docker run agentic-loop --task "..."` |
| From source | `pip install git+https://github.com/luohaha/AgenticLoop.git` |
