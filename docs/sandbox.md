# Sandbox Providers

Ouro can route command and file tools through an isolated sandbox instead of the host machine.

This first sandbox slice supports the **sandbox-as-a-tool** mode: ouro itself still runs on the host, while selected tools operate inside the configured sandbox.

## Supported Providers

| Provider | Install / Runtime | Notes |
|----------|-------------------|-------|
| `boxlite` | `pip install boxlite` | SDK-first adapter for BoxLite boxes. |
| `smolvm` | `pip install smolmachines` | SDK-first adapter using the embedded local engine; no `smolvm serve` process is required. |

Provider runtimes are not installed by ouro. Install and validate the provider you want to use before enabling sandbox tools.

## Configuration

Sandboxes are configured in `~/.ouro/sandboxes.yaml` (auto-created when `SandboxManager` first loads it).

```yaml
sandboxes:
  smolvm-local:
    provider: smolvm
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
| `working_dir` | No | Working directory shown to the agent; defaults to `/workspace` |
| `persist` | No | Whether provider state should persist when possible |
| `network.enabled` | No | Provider-specific network enable flag; defaults to `false` |
| `network.allow_hosts` | No | Provider-specific egress allowlist |
| `resources.cpu` / `resources.memory_mb` | No | Provider-specific resource hints |
| `volumes` | No | Host directory mounts when supported by the provider |

Unknown provider-specific fields are preserved in the profile `extra` map for future adapter support.

## Running with a Sandbox

Enable sandbox-backed tools for a one-shot task:

```bash
ouro --sandbox smolvm-local --task "Run python --version"
```

Use the current/default sandbox:

```bash
ouro --sandbox --task "Create and run a small Python script inside the sandbox"
```

If you do not pass `--sandbox`, tools run in the normal host mode.

Interactive mode also accepts `--sandbox` at startup:

```bash
ouro --sandbox boxlite-local
```

The selected sandbox is bound when the agent is created. Switching sandboxes mid-session is not implemented in this slice.

## Sandbox Tools

When sandbox is enabled, ouro keeps the normal tool names but backs filesystem/search/command tools with the selected sandbox:

| Tool name | Sandbox-backed behavior |
|-----------|-------------------------|
| `shell` | Execute shell commands inside the sandbox |
| `read_file` | Read sandbox files |
| `write_file` | Write sandbox files |
| `glob_files` | Glob sandbox files |
| `grep_content` | Search sandbox files |
| `smart_edit` | Edit sandbox files with diff preview/fuzzy matching |

Host implementations of `shell`, `read_file`, `write_file`, `smart_edit`, `glob_files`, and `grep_content` are not registered in sandbox mode. The agent can still use host-independent capabilities such as `web_search`, `web_fetch`, conversation search, memory tools, and task orchestration tools.

## Safety Notes

- Sandbox is opt-in. When enabled, host shell/file/edit/search tools are not exposed to the agent.
- Do not mount secrets or sensitive host directories into untrusted workloads.
- No host environment variables are forwarded by this first slice.
- Network should stay disabled unless the task requires it.
- File helper operations currently rely on commands executed inside the sandbox. Use images with Python installed (for example `python:3.12-slim` or `python:3.12-alpine`) for the best first-slice compatibility.

## Troubleshooting

### `BoxLite sandbox provider requires pip install boxlite`

Install the BoxLite Python SDK/runtime in the environment running ouro.

### `smol sandbox provider requires the smol-machines Python SDK`

Install the current smol-machines Python SDK with `pip install smolmachines`. The adapter uses the embedded local engine and does not require `smolvm serve start`.

### Sandbox files are missing

Host paths do not automatically exist inside the sandbox. Configure a supported volume mount or create files inside the sandbox with `write_file`.
