#!/usr/bin/env python3
"""Fail paid video preflight when provider and production model sets do not intersect."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PRODUCTION_ALLOWED_MODELS = ("seedance-2.0-fast", "seedance-2.0-pro", "MiniMax-H3")


def _episode_allowed_models(manifest: dict[str, Any]) -> set[str]:
    """Apply the series model migration contract at the paid gate itself."""
    episode = str(manifest.get("episode") or "")
    number = int(episode[1:]) if episode.startswith("E") and episode[1:].isdigit() else 0
    if number >= 45:
        return {"MiniMax-H3"}
    if number >= 41:
        return {"seedance-2.0-pro"}
    return {"seedance-2.0-fast"}


def _owner_scoped_allowed_models(
    manifest: dict[str, Any], tasks: list[dict[str, Any]]
) -> tuple[set[str] | None, list[dict[str, Any]]]:
    """Validate an exact-batch owner model override without widening policy.

    The durable submitter already validates each task-level override.  The
    provider gate runs earlier, so it must recognize the same contract while
    failing closed on partial, stale, or mismatched scopes.
    """
    override = manifest.get("production_model_override")
    if override is None:
        return None, []
    failures: list[dict[str, Any]] = []
    if not isinstance(override, dict):
        return None, [{"code": "OWNER_MODEL_OVERRIDE_INVALID", "reason": "NOT_OBJECT"}]
    authorization_ref = str(override.get("authorization_ref") or "").strip()
    allowed = {str(value) for value in override.get("allowed_models") or [] if str(value)}
    task_keys = {str(task.get("task_key") or "") for task in tasks}
    scoped_keys = {str(value) for value in override.get("task_keys") or [] if str(value)}
    if (
        override.get("schema") != "backlotos.owner_scoped_video_model_override.v1"
        or override.get("status") != "AUTHORIZED"
        or override.get("owner_authorized") is not True
        or not authorization_ref
    ):
        failures.append({"code": "OWNER_MODEL_OVERRIDE_INVALID", "reason": "AUTHORITY_CONTRACT"})
    if not allowed or not allowed.issubset(set(PRODUCTION_ALLOWED_MODELS)):
        failures.append({"code": "OWNER_MODEL_OVERRIDE_INVALID", "reason": "MODEL_SET", "models": sorted(allowed)})
    if not task_keys or scoped_keys != task_keys:
        failures.append({
            "code": "OWNER_MODEL_OVERRIDE_SCOPE_MISMATCH",
            "expected_task_keys": sorted(task_keys),
            "scoped_task_keys": sorted(scoped_keys),
        })
    for task in tasks:
        key = str(task.get("task_key") or "")
        model = str(task.get("model") or "")
        scoped = task.get("owner_scoped_model_override")
        valid = (
            isinstance(scoped, dict)
            and scoped.get("schema") == "backlotos.owner_scoped_video_model_override.v1"
            and scoped.get("status") == "AUTHORIZED"
            and scoped.get("owner_authorized") is True
            and str(scoped.get("authorization_ref") or "").strip() == authorization_ref
            and str(scoped.get("task_key") or "") == key
            and str(scoped.get("model") or "") == model
            and model in allowed
        )
        if not valid:
            failures.append({"code": "TASK_OWNER_MODEL_OVERRIDE_INVALID", "task_key": key})
    return (allowed if not failures else None), failures


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate_provider_capability(
    manifest: dict[str, Any],
    tasks: list[dict[str, Any]],
    *,
    registry_path: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(registry_path) if registry_path else Path(__file__).with_name("provider_video_capabilities.json")
    failures: list[dict[str, Any]] = []
    provider = str(manifest.get("provider") or "giggle")
    production_allowed_models = _episode_allowed_models(manifest)
    scoped_allowed_models, override_failures = _owner_scoped_allowed_models(manifest, tasks)
    failures.extend(override_failures)
    if scoped_allowed_models is not None:
        production_allowed_models = scoped_allowed_models
    requested_models = {
        str(value)
        for value in (manifest.get("allowed_video_models") or sorted(production_allowed_models))
        if str(value)
    }
    policy_expansion = requested_models - production_allowed_models
    if policy_expansion:
        failures.append({
            "code": "PRODUCTION_MODEL_POLICY_EXPANSION_FORBIDDEN",
            "requested_models": sorted(requested_models),
            "production_allowed_models": sorted(production_allowed_models),
        })
    allowed_models = requested_models & production_allowed_models
    registry: dict[str, Any] = {}
    if not path.is_file():
        failures.append({"code": "PROVIDER_CAPABILITY_REGISTRY_MISSING", "path": str(path)})
    else:
        try:
            registry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append({"code": "PROVIDER_CAPABILITY_REGISTRY_INVALID", "path": str(path), "error": str(exc)})

    provider_row = (registry.get("providers") or {}).get(provider) if registry else None
    if not isinstance(provider_row, dict):
        failures.append({"code": "PROVIDER_CAPABILITY_NOT_VERIFIED", "provider": provider})
        supported_models: set[str] = set()
    else:
        supported_models = {str(value) for value in provider_row.get("supported_models") or [] if str(value)}
        if not supported_models:
            failures.append({"code": "PROVIDER_SUPPORTED_MODEL_SET_EMPTY", "provider": provider})

    intersection = allowed_models & supported_models
    if allowed_models and supported_models and not intersection:
        failures.append({
            "code": "PROVIDER_ALLOWED_MODEL_INTERSECTION_EMPTY",
            "provider": provider,
            "allowed_models": sorted(allowed_models),
            "supported_models": sorted(supported_models),
        })
    for task in tasks:
        model = str(task.get("model") or "")
        if model and model not in allowed_models:
            failures.append({
                "code": "TASK_MODEL_OUTSIDE_PRODUCTION_ALLOWLIST",
                "task_key": task.get("task_key"),
                "model": model,
                "allowed_models": sorted(allowed_models),
            })
        if model and supported_models and model not in supported_models:
            failures.append({
                "code": "TASK_MODEL_UNSUPPORTED_BY_PROVIDER",
                "task_key": task.get("task_key"),
                "provider": provider,
                "model": model,
                "supported_models": sorted(supported_models),
            })
        model_capabilities = provider_row.get("model_capabilities") if isinstance(provider_row, dict) else None
        capability = model_capabilities.get(model) if isinstance(model_capabilities, dict) else None
        if model and model in supported_models and not isinstance(capability, dict):
            failures.append({
                "code": "PROVIDER_MODEL_CAPABILITY_MISSING",
                "task_key": task.get("task_key"),
                "provider": provider,
                "model": model,
            })
            continue
        allowed_resolutions = {
            str(value).lower()
            for value in ((capability or {}).get("resolutions") or [])
            if str(value)
        }
        resolution = str(task.get("resolution") or "").lower()
        if isinstance(capability, dict) and not resolution:
            failures.append({
                "code": "TASK_RESOLUTION_MISSING",
                "task_key": task.get("task_key"),
                "provider": provider,
                "model": model,
                "allowed_resolutions": sorted(allowed_resolutions),
            })
        elif resolution and allowed_resolutions and resolution not in allowed_resolutions:
            failures.append({
                "code": "TASK_RESOLUTION_UNSUPPORTED_BY_PROVIDER_MODEL",
                "task_key": task.get("task_key"),
                "provider": provider,
                "model": model,
                "resolution": resolution,
                "allowed_resolutions": sorted(allowed_resolutions),
            })

    return {
        "schema": "backlotos.provider_video_capability_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "provider": provider,
        "production_allowed_models": sorted(production_allowed_models),
        "requested_models": sorted(requested_models),
        "allowed_models": sorted(allowed_models),
        "supported_models": sorted(supported_models),
        "allowed_supported_intersection": sorted(intersection),
        "registry_path": str(path.resolve()),
        "registry_sha256": _sha256(path) if path.is_file() else None,
        "provider_evidence": provider_row if isinstance(provider_row, dict) else None,
        "owner_scoped_override_applied": scoped_allowed_models is not None,
        "failures": failures,
        "policy": "Paid video preflight binds the series migration contract: E40 and earlier use seedance-2.0-fast, E41-E44 use seedance-2.0-pro, and E45 onward use MiniMax-H3. The selected model must also be present in the verified provider registry and use an explicitly supported native resolution. Mini and the unpriced bare seedance-2.0 SKU remain forbidden.",
    }
