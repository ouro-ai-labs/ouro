# RFC: Reasoning Controls for LiteLLM Calls

Status: **Proposed**

## Problem Statement

`ouro` currently forwards generic kwargs to LiteLLM, but there is no explicit user-facing way to set reasoning depth per run (`reasoning_effort` / "Thinking Level").

As a result:
- users cannot intentionally trade quality vs latency/cost at runtime
- reasoning-capable models are underused
- CLI and interactive behavior are inconsistent

## Design Goals

1. Provide first-class runtime controls for reasoning behavior.
2. Keep current default behavior when no controls are set.
3. Reuse LiteLLM passthrough and avoid provider-specific branches in ouro.
4. Limit changes to CLI, interactive command handling, and agent call orchestration.

## Non-goals

- Migrating from `completion/acompletion` to another API surface.
- Model/provider-specific prompt tuning in this RFC.
- Applying reasoning controls to memory compression, long-term memory consolidation, or verifier calls.
- Adding a separate `verbosity` control (LiteLLM documents `verbosity` for some GPT-5 models, but this RFC focuses only on reasoning).
- Supporting the advanced OpenAI-only `reasoning_effort={"effort": "...", "summary": "..."}` form; this RFC only standardizes the string effort values.

## Functional Spec

### 1) Run-scoped options model (LiteLLM-aligned)

Add a run-scoped options object attached to the active agent/session:
- `reasoning_effort`: `default | none | minimal | low | medium | high | xhigh`

Wire format mapping:
- `default` -> omit `reasoning_effort`
- `none|minimal|low|medium|high|xhigh` -> `reasoning_effort=<same value>`

`default` means "do not send this field", so provider/model default behavior applies.

Notes:
- This RFC uses LiteLLM/OpenAI naming: `"none"` is the "no reasoning" effort value (some UIs may label this as "off").
- Not every model supports every value. Some models may reject certain values (e.g. only allowing `high`, or allowing `xhigh` only on specific snapshots). This is expected and is handled as an error (see Provider Compatibility / Validation).
- Persistence: run-scoped options are held in memory only. They are initialized at session start (CLI flag or default), can be changed interactively, and are not written back to config/profile storage in this RFC.

### 2) CLI contract

Add CLI flags:
- `--reasoning-effort {default,none,minimal,low,medium,high,xhigh,off}` (`off` is an alias for `none`)

Behavior:
- flags can be used in both `--task` mode and interactive mode bootstrapping
- when omitted, the session starts with `default`
- `off` is normalized to `none` for storage and display
- invalid values are rejected by argparse choice validation

### 3) Interactive contract

Add slash commands:
- `/reasoning <level>`

Where:
- `<level>` for `/reasoning`: `default|none|minimal|low|medium|high|xhigh` (plus `off` as an alias for `none`)

Semantics:
- updates apply immediately to subsequent primary task turns in the same session
- current value is shown in command success output
- invalid value prints usage and allowed values

Note:
- `reasoning_effort` (request steering) and any `show/hide thinking` display toggle remain independent controls.
- run-scoped `reasoning_effort` persists across model switches in the same session; it applies to subsequent primary task calls regardless of the active model until changed (e.g. `/reasoning default`).

Compatibility:
- Accept `/reasoning off` as an alias for `reasoning_effort=none` (UI-friendly), but persist/print the canonical value as `none`.

### 4) Effective request merge rule

For every primary loop LLM call, effective kwargs are merged in this order:

1. adapter/base call defaults
2. run-scoped `reasoning_effort` (if not `default`)
3. call-site explicit kwargs passed to `_call_llm(...)` (highest priority)

Pseudocode:

```python
effective = {}
effective.update(run_scoped_reasoning_kwargs())
effective.update(call_kwargs)
```

Where `run_scoped_reasoning_kwargs()` omits any key whose value is `default`/unset.

### 5) Scope of application

Apply the merge rule only to primary user-task calls in the ReAct loop:
- `agent/base.py::_react_loop` via `_call_llm(...)`

Do not apply to:
- `memory/compressor.py` calls
- `memory/long_term/consolidator.py` calls
- `agent/verification.py` calls

### 6) Capability discovery (LiteLLM)

We use LiteLLM introspection as best-effort hints for "which OpenAI-compatible params are supported" and "whether a model supports reasoning content".

In SDK mode, use:
- `litellm.get_supported_openai_params(model=..., custom_llm_provider=...)` to check if `reasoning_effort` is a supported parameter name for that provider/model.
- `litellm.supports_reasoning(model=..., custom_llm_provider=...)` to check if the model is expected to support `reasoning_content` / "thinking" behavior.

In Proxy mode (if `ouro` is pointed at a LiteLLM proxy), similar information can be obtained via:
- `GET /utils/supported_openai_params?model=...`
- `GET /model_group/info` and `GET /v1/model/info`

This RFC does **not** attempt to derive a full per-model "supported reasoning_effort values" matrix from LiteLLM, because LiteLLM does not expose that as a single uniform introspection API today.

Important:
- ouro does not gate sending `reasoning_effort` on `supports_reasoning()`. `supports_reasoning()` can be incomplete or model-name dependent, and some providers use `reasoning_effort` as a control knob even when they do not return `reasoning_content`.

### 7) Provider compatibility, validation, and failure behavior

- ouro passes parameters as best effort via LiteLLM.
- ouro defaults to `drop_params=True` (keep current behavior): prefer "requests succeed" over strict validation.
- With `drop_params=True`, **unsupported parameter names** are silently dropped by LiteLLM (e.g. if a provider does not support `reasoning_effort` at all).
- `drop_params` does **not** guarantee safety for invalid parameter **values**. Some providers/models reject specific `reasoning_effort` values (for example, `xhigh` only on some models; `none` not supported by some Azure GPT-5 deployments).
- LiteLLM may enforce some of these constraints locally and raise `litellm.UnsupportedParamsError` or other errors before a network request is made.
- No provider-specific "auto-downgrade and retry" logic is added in this RFC; errors are surfaced to the user as-is.

Operational notes:
- If you want to reliably *see* an error when a model/provider does not support `reasoning_effort` as a parameter name, run with `drop_params=False` (strict mode). With `drop_params=True`, LiteLLM may drop the parameter name and the request can still succeed, which can look like "the setting was ignored".
- When the active model changes mid-session, `reasoning_effort` can become unsupported for the new model. In strict mode this can raise; in drop mode this can be silently removed. Either way, users can reset to provider defaults via `/reasoning default`.
- UX recommendation (interactive): when the active model changes, and `drop_params=True` and `litellm.get_supported_openai_params()` does not include `reasoning_effort`, display a one-line warning that the setting may be ignored/dropped for the current model.

## Proposed Code Changes

- `main.py`
  - parse `--reasoning-effort`
  - pass run-scoped options into agent/session initialization
- `agent/base.py` (or `agent/agent.py`)
  - store run-scoped reasoning options on agent
  - merge options into primary `_call_llm(...)` path
- `interactive.py`
  - register `/reasoning` command and Reasoning Effort picker UI
  - parse/validate/update session run-scoped options
- docs
  - update `README.md`, `docs/configuration.md`, `docs/examples.md`

## Testing Plan

1. CLI parsing tests for `--reasoning-effort` and allowed values.
2. Agent merge tests: explicit kwargs > run-scoped values > default.
3. Scope tests: primary loop inherits options; compressor/consolidator/verifier do not.
4. Interactive command tests for `/reasoning` validation and state updates.
5. Model switch behavior tests: run-scoped value persists; `default` omits the parameter; `off` normalizes to `none`.

## Success Criteria

- Users can configure reasoning controls from CLI and interactive commands.
- Primary task turns send the expected parameters when configured.
- Existing workflows are unchanged when all controls are `default`.
- Tests verify merge precedence and propagation boundaries.
