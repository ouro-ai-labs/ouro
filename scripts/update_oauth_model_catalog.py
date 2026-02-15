#!/usr/bin/env python3
"""Update OAuth model catalog from published pi-ai package.

This script fetches @mariozechner/pi-ai from npm, extracts `dist/models.generated.js`,
reads the `openai-codex` provider model IDs, maps them to `chatgpt/*`, and rewrites
`llm/oauth_model_catalog.py`.
"""

from __future__ import annotations

import argparse
import io
import json
import tarfile
import urllib.request
from pathlib import Path

NPM_PKG = "@mariozechner/pi-ai"
NPM_REGISTRY = "https://registry.npmjs.org"
PI_PROVIDER_ID = "openai-codex"
OURO_PROVIDER_ID = "chatgpt"
DIST_MODELS_PATH_SUFFIX = "package/dist/models.generated.js"


def _http_json(url: str) -> dict:
    with urllib.request.urlopen(url) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8"))


def _http_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url) as r:  # noqa: S310
        return r.read()


def _resolve_npm_release(version: str | None) -> tuple[str, str]:
    if version:
        data = _http_json(f"{NPM_REGISTRY}/{NPM_PKG}/{version}")
        return data["version"], data["dist"]["tarball"]

    data = _http_json(f"{NPM_REGISTRY}/{NPM_PKG}/latest")
    return data["version"], data["dist"]["tarball"]


def _extract_models_generated_js(tgz: bytes) -> str:
    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tf:
        member = next(
            (m for m in tf.getmembers() if m.name.endswith(DIST_MODELS_PATH_SUFFIX)), None
        )
        if member is None:
            raise RuntimeError(f"Could not find {DIST_MODELS_PATH_SUFFIX} in npm tarball")

        f = tf.extractfile(member)
        if f is None:
            raise RuntimeError(f"Failed to extract {member.name}")

        return f.read().decode("utf-8")


def _extract_provider_block(models_js: str, provider_id: str) -> str:
    marker = f'"{provider_id}":'
    idx = models_js.find(marker)
    if idx < 0:
        raise RuntimeError(f"Provider '{provider_id}' not found in models.generated.js")

    brace_start = models_js.find("{", idx)
    if brace_start < 0:
        raise RuntimeError(f"Malformed provider block for '{provider_id}'")

    depth = 0
    in_string = False
    escaped = False

    for i in range(brace_start, len(models_js)):
        ch = models_js[i]

        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return models_js[brace_start + 1 : i]

    raise RuntimeError(f"Unclosed provider block for '{provider_id}'")


def _extract_provider_model_ids(provider_block: str) -> list[str]:
    """Extract first-level model IDs from a provider object block.

    We parse object keys at depth 0 only, so nested object keys are ignored.
    """
    out: list[str] = []
    seen: set[str] = set()

    i = 0
    depth = 0
    n = len(provider_block)

    while i < n:
        ch = provider_block[i]

        if depth == 0 and ch == '"':
            # Parse key string.
            j = i + 1
            while j < n:
                if provider_block[j] == '"' and provider_block[j - 1] != "\\":
                    break
                j += 1
            if j >= n:
                break

            key = provider_block[i + 1 : j]
            k = j + 1
            while k < n and provider_block[k].isspace():
                k += 1

            if k < n and provider_block[k] == ":":
                k += 1
                while k < n and provider_block[k].isspace():
                    k += 1
                if k < n and provider_block[k] == "{" and key not in seen:
                    seen.add(key)
                    out.append(key)

            i = j + 1
            continue

        if ch == "{":
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1

        i += 1

    return out


def _render_catalog_module(pi_ai_version: str, model_ids: list[str]) -> str:
    chatgpt_ids = [f"{OURO_PROVIDER_ID}/{mid}" for mid in model_ids]

    lines = [
        '"""OAuth model catalog used to seed `~/.ouro/models.yaml` after login.',
        "",
        "This file is intentionally deterministic and runtime-offline.",
        "",
        "To refresh from pi-ai's latest published model registry, run:",
        "",
        "    python scripts/update_oauth_model_catalog.py",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        f'PI_AI_VERSION = "{pi_ai_version}"',
        f'PI_AI_PROVIDER_ID = "{PI_PROVIDER_ID}"',
        "",
        "# Synced from pi-ai openai-codex provider model IDs, mapped to ouro's chatgpt/*",
        "# LiteLLM provider namespace.",
        "OAUTH_PROVIDER_MODEL_IDS: dict[str, tuple[str, ...]] = {",
        f'    "{OURO_PROVIDER_ID}": (',
    ]

    lines.extend(f'        "{model_id}",' for model_id in chatgpt_ids)

    lines.extend(
        [
            "    ),",
            "}",
            "",
            "",
            "def get_oauth_provider_model_ids(provider: str) -> tuple[str, ...]:",
            "    try:",
            "        return OAUTH_PROVIDER_MODEL_IDS[provider]",
            "    except KeyError as e:",
            '        raise ValueError(f"Unsupported provider: {provider}") from e',
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi-ai-version", help="Pin specific @mariozechner/pi-ai version")
    parser.add_argument(
        "--output",
        default="llm/oauth_model_catalog.py",
        help="Output module path (default: llm/oauth_model_catalog.py)",
    )
    args = parser.parse_args()

    version, tarball_url = _resolve_npm_release(args.pi_ai_version)
    tgz = _http_bytes(tarball_url)
    models_js = _extract_models_generated_js(tgz)
    provider_block = _extract_provider_block(models_js, PI_PROVIDER_ID)
    model_ids = _extract_provider_model_ids(provider_block)
    if not model_ids:
        raise RuntimeError("No model IDs extracted from openai-codex provider block")

    content = _render_catalog_module(version, model_ids)

    output = Path(args.output)
    output.write_text(content, encoding="utf-8")

    print(f"Updated {output}")
    print(f"pi-ai version: {version}")
    print(f"{PI_PROVIDER_ID} models: {len(model_ids)}")


if __name__ == "__main__":
    main()
