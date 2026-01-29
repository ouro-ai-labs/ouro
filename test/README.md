# Tests

This directory contains test files for the AgenticLoop project.

## Test Files

- `test_basic.py` - Basic functionality tests for tools and imports
- `test_memory.py` - Memory management system demonstration and tests

## Running Tests

### Prerequisites

Bootstrap a local dev environment (recommended):

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
```

### Run Individual Tests

From the project root directory:

```bash
# Run a subset (fast)
python3 -m pytest test/test_basic.py -q
python3 -m pytest test/memory/ -q
```

### Run All Tests

```bash
# From project root
python3 -m pytest test/
```

## Test Coverage

- **test_basic.py**: Tests basic tool functionality, imports, and API key configuration
- **test_memory.py**: Demonstrates memory compression and token tracking features

## Notes

- Live LLM integration tests are skipped by default (set `RUN_INTEGRATION_TESTS=1` to enable).
- Set up your `.aloop/config` file before running tests that require API access
- Memory tests use a mock LLM and don't require API keys
