#!/usr/bin/env python3
"""Require native formal-release resolution instead of cosmetic upscaling."""

from __future__ import annotations
from typing import Any

HEIGHTS = {"480p": 480, "720p": 720, "1080p": 1080, "4k": 2160}


def evaluate_batch(config: dict[str, Any]) -> dict[str, Any]:
    minimum = int(config.get("minimum_native_generation_height") or 0)
    failures, rows = [], []
    if not minimum:
        return {"schema": "qingshan.delivery_resolution_gate.v1", "status": "PASS", "rows": [], "failures": [], "policy": "Not enabled for this batch."}
    for task in config.get("tasks") or []:
        if task.get("tool_type", "video_generation") != "video_generation":
            continue
        key = str(task.get("task_key") or "UNKNOWN")
        resolution = str(task.get("resolution") or "").lower()
        height = HEIGHTS.get(resolution, 0)
        rows.append({"task_key": key, "resolution": resolution, "native_height": height})
        if height < minimum:
            failures.append({"code": "NATIVE_GENERATION_RESOLUTION_BELOW_RELEASE_FLOOR", "task_key": key, "actual": resolution, "minimum_height": minimum})
        if task.get("resolution_source") == "UPSCALED_FROM_LOWER_RESOLUTION":
            failures.append({"code": "COSMETIC_UPSCALE_CANNOT_SATISFY_NATIVE_RESOLUTION", "task_key": key})
    return {"schema": "qingshan.delivery_resolution_gate.v1", "status": "PASS" if not failures else "FAIL", "rows": rows, "failures": failures, "policy": "Formal replacements must be generated natively at or above the declared height."}
