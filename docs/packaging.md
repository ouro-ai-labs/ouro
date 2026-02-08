# Packaging and Distribution

## Local Development

Prerequisites: Python 3.12+ and [uv](https://github.com/astral-sh/uv).

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
ouro --help
```

## Building

```bash
./scripts/dev.sh build
```

Creates `dist/ouro-*.whl` and `dist/ouro-*.tar.gz`.

Test locally:
```bash
pip install dist/ouro-*.whl
ouro --task "Calculate 1+1"
```

## Publishing to PyPI

### Automated (recommended)

Pushing a `v*` tag triggers the GitHub Actions release workflow, which runs the
full test suite, builds the package, publishes to PyPI via Trusted Publisher, and
creates a GitHub Release.

```bash
git tag v0.2.0
git push --tags
```

### Manual — Test PyPI (recommended first)

```bash
./scripts/dev.sh publish --test
pip install --index-url https://test.pypi.org/simple/ ouro
```

### Manual — Production PyPI

```bash
./scripts/dev.sh publish
```

`publish` is interactive by default and refuses to run without a TTY unless you pass `--yes`.

## Docker

### Build

```bash
docker build -t ouro:latest .
```

### Run

Mount `.ouro/` to provide model configuration:

```bash
# Interactive mode
docker run -it --rm \
  -v $(pwd)/.ouro:/app/.ouro \
  ouro

# Single task
docker run --rm \
  -v $(pwd)/.ouro:/app/.ouro \
  ouro --task "Calculate 1+1"
```

### Publish

```bash
docker tag ouro:latest yourusername/ouro:0.1.0
docker tag ouro:latest yourusername/ouro:latest
docker push yourusername/ouro:0.1.0
docker push yourusername/ouro:latest
```

## Release Checklist

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md` (move items from `[Unreleased]` to the new version)
3. Run checks: `./scripts/dev.sh check`
4. Open a PR, get it merged to `main`
5. Tag the release: `git tag v0.x.0 && git push --tags`
6. GitHub Actions automatically: tests -> build -> publish to PyPI -> create GitHub Release
7. Verify the release on [pypi.org](https://pypi.org/project/ouro/) and GitHub Releases

## Distribution Summary

| Method | Command |
|--------|---------|
| Local dev | `./scripts/bootstrap.sh` |
| Docker | `docker run ouro --task "..."` |
| From source | `pip install git+https://github.com/ouro-ai-labs/ouro.git` |
