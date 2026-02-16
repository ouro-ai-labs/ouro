# Tests

This directory contains test files for the ouro project.

## Quickstart

```bash
./scripts/bootstrap.sh
./scripts/dev.sh test -q
```

## Running Tests

### Run a Single Test File / Test Case

```bash
# Single file (fast)
./scripts/dev.sh test -q test/test_shell.py

# Single test (nodeid)
./scripts/dev.sh test -q test/test_shell.py::test_command_timeout
```

### Run a Test Folder (Suite)

```bash
./scripts/dev.sh test -q test/memory/
```

```bash
# All tests
./scripts/dev.sh test
```

### Integration (Live LLM) Tests

```bash
RUN_INTEGRATION_TESTS=1 ./scripts/dev.sh test -q -m integration
```

## Notes

- Live LLM integration tests are skipped by default; enabling them may incur cost.
- Some CLI smoke runs (outside pytest) require a configured provider in `~/.ouro/models.yaml`.
- Prefer targeted tests during iteration; run `./scripts/dev.sh check` before asking for review/merge.
