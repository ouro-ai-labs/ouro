"""Sync OAuth-managed models into `~/.ouro/models.yaml`.

This keeps ouro's YAML-first model selection UX while allowing OAuth login
flows to expose provider models in `/model`.
"""

from __future__ import annotations

from llm.model_manager import ModelManager, ModelProfile
from llm.oauth_model_catalog import get_oauth_provider_model_ids


def _get_provider_model_ids(provider: str) -> tuple[str, ...]:
    return get_oauth_provider_model_ids(provider)


def _is_managed_profile(profile: ModelProfile, provider: str) -> bool:
    return (
        profile.extra.get("oauth_managed") is True
        and profile.extra.get("oauth_provider") == provider
    )


def sync_oauth_models(model_manager: ModelManager, provider: str) -> list[str]:
    """Ensure OAuth provider models are present in model config.

    Returns:
        List of newly added model IDs.
    """
    model_ids = _get_provider_model_ids(provider)
    added: list[str] = []
    changed = False

    for model_id in model_ids:
        if model_id in model_manager.models:
            continue

        model_manager.models[model_id] = ModelProfile(
            model_id=model_id,
            timeout=600,
            drop_params=True,
            extra={"oauth_managed": True, "oauth_provider": provider},
        )
        added.append(model_id)
        changed = True

    if model_manager.default_model_id is None and model_ids:
        model_manager.default_model_id = model_ids[0]
        changed = True

    if model_manager.current_model_id is None and model_manager.default_model_id:
        model_manager.current_model_id = model_manager.default_model_id

    if changed:
        model_manager._save()

    return added


def remove_oauth_models(model_manager: ModelManager, provider: str) -> list[str]:
    """Remove OAuth-managed provider models from model config.

    Only models previously auto-inserted by oauth sync are removed.

    Returns:
        List of removed model IDs.
    """
    # Validate provider.
    _get_provider_model_ids(provider)

    removed: list[str] = []
    changed = False

    for model_id, profile in list(model_manager.models.items()):
        if not _is_managed_profile(profile, provider):
            continue

        del model_manager.models[model_id]
        removed.append(model_id)
        changed = True

    if not changed:
        return removed

    if model_manager.default_model_id not in model_manager.models:
        model_manager.default_model_id = next(iter(model_manager.models.keys()), None)

    if model_manager.current_model_id not in model_manager.models:
        model_manager.current_model_id = model_manager.default_model_id

    model_manager._save()
    return removed
