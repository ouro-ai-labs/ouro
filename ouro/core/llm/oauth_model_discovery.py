"""Runtime OAuth model discovery for subscription-backed providers."""

from __future__ import annotations

import io
import json
import re
import tarfile
import urllib.request
from contextlib import suppress

from ouro.config import Config

NPM_PKG = "@mariozechner/pi-ai"
NPM_REGISTRY = "https://registry.npmjs.org"
PI_PROVIDER_ID = "openai-codex"
OURO_CHATGPT_PROVIDER_ID = "chatgpt"
PI_DIST_MODELS_PATH_SUFFIX = "package/dist/models.generated.js"
GITHUB_COPILOT_MODELS_MARKDOWN_URL = (
    "https://docs.github.com/api/article/body"
    "?pathname=/en/copilot/reference/ai-models/supported-models&m=1"
)

OFFICIAL_CHATGPT_SUBSCRIPTION_MODEL_IDS = (
    "gpt-5.3-instant",
    "gpt-5.4-pro",
)


def _get_timeout_seconds() -> float:
    with suppress(TypeError, ValueError):
        value = float(Config.OAUTH_MODEL_REFRESH_TIMEOUT_SECONDS)
        if value > 0:
            return value
    return 10.0


def _http_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=_get_timeout_seconds()) as r:  # noqa: S310
        return r.read().decode("utf-8")


def _http_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=_get_timeout_seconds()) as r:  # noqa: S310
        return r.read()


def _merge_model_ids(primary: list[str], additional: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for model_id in [*primary, *additional]:
        if model_id in seen:
            continue
        seen.add(model_id)
        out.append(model_id)
    return out


def _extract_pi_provider_block(models_js: str, provider_id: str) -> str:
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


def _extract_pi_provider_model_ids(provider_block: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    i = 0
    depth = 0
    n = len(provider_block)

    while i < n:
        ch = provider_block[i]

        if depth == 0 and ch == '"':
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


def _filter_chatgpt_model_ids_for_litellm(model_ids: list[str]) -> list[str]:
    try:
        import litellm  # type: ignore
    except Exception:
        return model_ids

    supported = getattr(litellm, "chatgpt_models", None)
    if not isinstance(supported, (set, list, tuple)):
        return model_ids

    supported_ids = {str(x) for x in supported}
    return [mid for mid in model_ids if f"{OURO_CHATGPT_PROVIDER_ID}/{mid}" in supported_ids]


def discover_chatgpt_model_ids() -> tuple[str, ...]:
    """Discover current ChatGPT subscription model IDs."""
    latest = json.loads(_http_text(f"{NPM_REGISTRY}/{NPM_PKG}/latest"))
    tarball_url = latest["dist"]["tarball"]
    tgz = _http_bytes(tarball_url)

    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tf:
        member = next(
            (m for m in tf.getmembers() if m.name.endswith(PI_DIST_MODELS_PATH_SUFFIX)),
            None,
        )
        if member is None:
            raise RuntimeError(f"Could not find {PI_DIST_MODELS_PATH_SUFFIX} in npm tarball")

        f = tf.extractfile(member)
        if f is None:
            raise RuntimeError(f"Failed to extract {member.name}")

        models_js = f.read().decode("utf-8")

    provider_block = _extract_pi_provider_block(models_js, PI_PROVIDER_ID)
    model_ids = _extract_pi_provider_model_ids(provider_block)
    model_ids = _merge_model_ids(model_ids, OFFICIAL_CHATGPT_SUBSCRIPTION_MODEL_IDS)
    model_ids = _filter_chatgpt_model_ids_for_litellm(model_ids)
    if not model_ids:
        raise RuntimeError("No compatible ChatGPT subscription models discovered")
    return tuple(f"{OURO_CHATGPT_PROVIDER_ID}/{mid}" for mid in model_ids)


_COPILOT_NAME_OVERRIDES = {
    "claude opus 4.1": "claude-opus-41",
    "claude opus 4.6 fast mode preview": "claude-opus-4.6-fast",
    "gemini 3 pro": "gemini-3-pro-preview",
}


def _normalize_copilot_model_name(name: str) -> str:
    name = re.sub(r"\[\^[^\]]+\]", "", name)
    name = re.sub(r"<[^>]+>", "", name)
    name = name.replace("(", " ").replace(")", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _copilot_model_name_to_id(name: str) -> str | None:
    normalized = _normalize_copilot_model_name(name)
    if not normalized or normalized.lower() in {"model", "available models"}:
        return None

    key = normalized.lower()
    if key in _COPILOT_NAME_OVERRIDES:
        return f"github_copilot/{_COPILOT_NAME_OVERRIDES[key]}"

    model = key.replace(".", ".").replace("/", "-")
    model = re.sub(r"[^a-z0-9.]+", "-", model).strip("-")
    if not model:
        return None
    return f"github_copilot/{model}"


def _extract_copilot_model_names(markdown: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for line in markdown.splitlines():
        if not line.startswith("| "):
            continue
        columns = [col.strip() for col in line.strip("|").split("|")]
        if not columns:
            continue
        name = _normalize_copilot_model_name(columns[0])
        if not name or name.lower() in {"model", "model name", "available models"}:
            continue
        if set(name) == {"-"}:
            continue
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def discover_copilot_model_ids() -> tuple[str, ...]:
    """Discover current GitHub Copilot subscription model IDs from GitHub Docs."""
    markdown = _http_text(GITHUB_COPILOT_MODELS_MARKDOWN_URL)
    model_ids = [
        model_id
        for name in _extract_copilot_model_names(markdown)
        if (model_id := _copilot_model_name_to_id(name)) is not None
    ]
    if not model_ids:
        raise RuntimeError("No Copilot subscription models discovered")
    return tuple(model_ids)


def discover_oauth_provider_model_ids(provider: str) -> tuple[str, ...]:
    if provider == "chatgpt":
        return discover_chatgpt_model_ids()
    if provider == "copilot":
        return discover_copilot_model_ids()
    raise ValueError(f"Unsupported provider: {provider}")
