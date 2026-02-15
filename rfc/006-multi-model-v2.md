# RFC: Multi-Model Configuration and Runtime Switching (v2)

Status: **Completed** (2026-01-30)

## Problem Statement

ouro historically behaves like a single-model app. Users need to:
- Configure multiple models (different providers / endpoints / keys)
- Switch the active model in interactive mode
- Keep secrets out of git by default

## Design Goals

1. **Multiple Models**: Configure multiple LiteLLM model IDs.
2. **Runtime Switching**: Switch models in interactive mode with a simple UX.
3. **YAML-First**: Depend on `.ouro/models.yaml` only (no env/legacy config).
4. **Minimal Commands**: Avoid a large `/model` subcommand surface.
5. **Secret Safety**: Config is gitignored and file-permission hardened where possible.
6. **No Backward Compatibility**: Clean slate; users migrate manually.

## Proposed Solution

### 1. Configuration Format (YAML)

File: `.ouro/models.yaml` (gitignored)

```yaml
# Model Configuration
# This file is gitignored - do not commit to version control
#
# The key under `models` is the LiteLLM model ID: provider/model-name

models:
  anthropic/claude-3-5-sonnet-20241022:
    api_key: sk-ant-...
    timeout: 600
    drop_params: true

  openai/gpt-4o:
    api_key: sk-...
    timeout: 300

  # Local model example (no API key needed)
  ollama/llama2:
    api_base: http://localhost:11434

default: anthropic/claude-3-5-sonnet-20241022
```

Fields per model:
- `api_key` (required for most hosted providers)
- `api_base` (optional; custom endpoint/proxy)
- `timeout` (optional; seconds; default 600)
- `drop_params` (optional; default true)

### 2. Model Manager

`ModelManager` loads/saves `.ouro/models.yaml` and tracks:
- `models: dict[model_id, profile]`
- `default_model_id`
- `current_model_id`

Behavior:
- Create a template file on first run.
- Atomic writes to prevent corruption.
- Attempt to set file mode to `0600` (best-effort).
- Ignore deprecated fields like `name` if present (and do not write them back).

### 3. Interactive Mode UX

Keep only two commands:

```
/model       - Open a TUI picker (↑/↓ + Enter; Esc cancels)
/model edit  - Open `.ouro/models.yaml` and auto-reload after save
```

When no models are configured, `/model` should show an actionable reminder:
“No models configured yet. Run `/model edit` to configure `.ouro/models.yaml`.”

### 4. CLI Flag

Support selecting a configured model at startup:

```bash
python main.py --task "Hello" --model openai/gpt-4o
python main.py --model openai/gpt-4o
```

### 5. Git Protection

`.ouro/models.yaml` must be in `.gitignore` by default.

## Key Design Decisions

### 1. No `name` Field

The YAML schema does not include `name`. The canonical identifier is the LiteLLM `model_id`.

If an old YAML contains `name`, it is ignored (so existing local configs don’t crash) and removed on the next save.

### 2. “Edit the YAML” Instead of “Command API”

Most model operations (add/remove/default) are config edits. Keeping them in one place:
- reduces duplication and parsing logic
- keeps the CLI surface small
- makes the workflow transparent

### 3. No ENV/Legacy Compatibility

The system does not attempt to read previous env-based or legacy model config formats.

## Success Criteria

- Users can configure multiple models in `.ouro/models.yaml`
- Interactive mode can switch models via a picker
- Editing YAML reloads without restarting the app
- Secrets are gitignored by default and file permissions are tightened where possible
