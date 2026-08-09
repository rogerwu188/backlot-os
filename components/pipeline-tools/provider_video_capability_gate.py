#!/usr/bin/env python3
"""Fail paid video preflight when provider and production model sets do not intersect."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PRODUCTION_ALLOWED_MODELS = ("seedance-2.0-fast",)


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
    production_allowed_models = set(PRODUCTION_ALLOWED_MODELS)
    requested_models = {
        str(value)
        for value in (manifest.get("allowed_video_models") or PRODUCTION_ALLOWED_MODELS)
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
        "failures": failures,
        "policy": "Paid video preflight fails before provider POST unless the current task model is seedance-2.0-fast, is requested by the manifest, is verified as supported by the selected provider, and uses a resolution explicitly allowed for that provider/model. Pro, Mini, and the unpriced bare seedance-2.0 SKU cannot be enabled by a manifest.",
    }
