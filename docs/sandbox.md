# Sandbox Providers

Ouro can expose optional `sandbox_*` tools that run commands and file operations inside an isolated sandbox instead of on the host machine.

This first sandbox slice supports the **sandbox-as-a-tool** mode: ouro itself still runs on the host, while selected tools operate inside the configured sandbox.

## Supported Providers

| Provider | Install / Runtime | Notes |
|----------|-------------------|-------|
| `boxlite` | `pip install boxlite` | SDK-first adapter for BoxLite boxes. |
| `smolvm` | `pip install smolvm` plus a running smolvm server | SDK-first adapter; default server is `http://127.0.0.1:8080`. |

Provider runtimes are not installed by ouro. Install and validate the provider you want to use before enabling sandbox tools.

## Configuration

Sandboxes are configured in `~/.ouro/sandboxes.yaml` (auto-created when `SandboxManager` first loads it).

```yaml
sandboxes:
  smolvm-local:
    provider: smolvm
    api_url: http://127.0.0.1:8080
    image: python:3.12-alpine
    working_dir: /workspace
    persist: true
    network:
      enabled: false
      allow_hosts: []
    resources:
      cpu: 2
      memory_mb: 4096
    volumes:
      - source: .
        target: /workspace
        mode: rw

  boxlite-local:
    provider: boxlite
    image: python:3.12-slim
    working_dir: /workspace
    persist: true
    network:
      enabled: false
      allow_hosts: []

default: smolvm-local
current: smolvm-local
```

### Fields

| Field | Required | Description |
|-------|----------|-------------|
| `provider` | Yes | `boxlite` or `smolvm` |
| `image` | Yes | OCI image used by the provider |
| `api_url` | smolvm only when non-default | smolvm server URL |
| `working_dir` | No | Working directory shown to the agent; defaults to `/workspace` |
| `persist` | No | Whether provider state should persist when possible |
| `network.enabled` | No | Provider-specific network enable flag; defaults to `false` |
| `network.allow_hosts` | No | Provider-specific egress allowlist |
| `resources.cpu` / `resources.memory_mb` | No | Provider-specific resource hints |
| `volumes` | No | Host directory mounts when supported by the provider |

Unknown provider-specific fields are preserved in the profile `extra` map for future adapter support.

## Running with a Sandbox

Enable sandbox tools for a one-shot task:

```bash
ouro --sandbox smolvm-local --task "Use sandbox_shell to run python --version"
```

Use the current/default sandbox:

```bash
ouro --sandbox --task "Create and run a small Python script inside the sandbox"
```

If you do not pass `--sandbox`, sandbox tools are not enabled.

Interactive mode also accepts `--sandbox` at startup:

```bash
ouro --sandbox boxlite-local
```

The selected sandbox is bound when the agent is created. Switching sandboxes mid-session is not implemented in this slice.

## Sandbox Tools

When sandbox is enabled, ouro registers sandbox-scoped replacements for filesystem/search/command tools:

| Tool | Runs inside sandbox |
|------|---------------------|
| `sandbox_shell` | Execute shell commands |
| `sandbox_read_file` | Read sandbox files |
| `sandbox_write_file` | Write sandbox files |
| `sandbox_glob_files` | Glob sandbox files |
| `sandbox_grep_content` | Search sandbox files |
| `sandbox_smart_edit` | Edit sandbox files with diff preview/fuzzy matching |

In sandbox mode, host `shell`, `read_file`, `write_file`, `smart_edit`, `glob_files`, and `grep_content` are not registered. The agent can still use host-independent capabilities such as `web_search`, `web_fetch`, conversation search, memory tools, and task orchestration tools.

## Safety Notes

- Sandbox is opt-in. When enabled, host shell/file/edit/search tools are not exposed to the agent.
- Do not mount secrets or sensitive host directories into untrusted workloads.
- No host environment variables are forwarded by this first slice.
- Network should stay disabled unless the task requires it.
- File helper operations currently rely on commands executed inside the sandbox. Use images with Python installed (for example `python:3.12-slim` or `python:3.12-alpine`) for the best first-slice compatibility.

## Troubleshooting

### `BoxLite sandbox provider requires pip install boxlite`

Install the BoxLite Python SDK/runtime in the environment running ouro.

### `smolvm sandbox provider requires pip install smolvm and a running smolvm server`

Install the smolvm Python SDK and start/verify the smolvm server. The default SDK endpoint is `http://127.0.0.1:8080` unless `api_url` is configured.

### Sandbox files are missing

Host paths do not automatically exist inside the sandbox. Configure a supported volume mount or create/upload files inside the sandbox with `sandbox_write_file`.
