#!/usr/bin/env python3
"""Fail paid video preflight when provider and production model sets do not intersect."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_ALLOWED_MODELS = ("seedance-2.0",)


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
    allowed_models = {
        str(value) for value in (manifest.get("allowed_video_models") or DEFAULT_ALLOWED_MODELS) if str(value)
    }
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

    return {
        "schema": "backlotos.provider_video_capability_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "provider": provider,
        "allowed_models": sorted(allowed_models),
        "supported_models": sorted(supported_models),
        "allowed_supported_intersection": sorted(intersection),
        "registry_path": str(path.resolve()),
        "registry_sha256": _sha256(path) if path.is_file() else None,
        "provider_evidence": provider_row if isinstance(provider_row, dict) else None,
        "failures": failures,
        "policy": "Paid video preflight fails before provider POST unless the current task model is both production-allowed and verified as supported by the selected provider.",
    }
