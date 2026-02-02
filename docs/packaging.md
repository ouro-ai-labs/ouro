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

Creates `dist/aloop-*.whl` and `dist/aloop-*.tar.gz`.

Test locally:
```bash
pip install dist/aloop-*.whl
aloop --task "Calculate 1+1"
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

See **Trusted Publisher Setup** below for one-time PyPI configuration.

### Manual — Test PyPI (recommended first)

```bash
./scripts/dev.sh publish --test
pip install --index-url https://test.pypi.org/simple/ aloop
```

### Manual — Production PyPI

```bash
./scripts/dev.sh publish
```

`publish` is interactive by default and refuses to run without a TTY unless you pass `--yes`.

## Trusted Publisher Setup (one-time)

The release workflow uses [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/)
so no API tokens are needed. Configure it once on pypi.org:

1. Log in to [pypi.org](https://pypi.org) and navigate to the project settings.
2. Go to **Publishing** > **Add a new publisher**.
3. Select **GitHub** and fill in:
   - Owner: `luohaha`
   - Repository: `aloop`
   - Workflow name: `release.yml`
   - Environment: `release`
4. Save. Subsequent tag pushes will authenticate automatically.

## Docker

### Build

```bash
docker build -t aloop:latest .
```

### Run

Mount `.aloop/` to provide model configuration:

```bash
# Interactive mode
docker run -it --rm \
  -v $(pwd)/.aloop:/app/.aloop \
  aloop

# Single task
docker run --rm \
  -v $(pwd)/.aloop:/app/.aloop \
  aloop --task "Calculate 1+1"
```

### Publish

```bash
docker tag aloop:latest yourusername/aloop:0.1.0
docker tag aloop:latest yourusername/aloop:latest
docker push yourusername/aloop:0.1.0
docker push yourusername/aloop:latest
```

## Release Checklist

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md` (move items from `[Unreleased]` to the new version)
3. Run checks: `./scripts/dev.sh check`
4. Open a PR, get it merged to `main`
5. Tag the release: `git tag v0.x.0 && git push --tags`
6. GitHub Actions automatically: tests -> build -> publish to PyPI -> create GitHub Release
7. Verify the release on [pypi.org](https://pypi.org/project/aloop/) and GitHub Releases

## Distribution Summary

| Method | Command |
|--------|---------|
| Local dev | `./scripts/bootstrap.sh` |
| Docker | `docker run aloop --task "..."` |
| From source | `pip install git+https://github.com/luohaha/aloop.git` |
