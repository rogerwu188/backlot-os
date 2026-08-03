#!/usr/bin/env python3
"""Reject repetitive or unmotivated camera motion before provider submission."""

from __future__ import annotations
import re
from typing import Any

MOTION_PATTERNS = {
    "oscillation": re.compile(r"smooth[_ -]?roam|camera sway|摇摆|来回摇|周期(?:性)?运镜|sin\s*\(", re.I),
    "push": re.compile(r"slow[_ -]?push|push[_ -]?in|dolly[_ -]?in|慢推|缓慢推近", re.I),
    "reveal": re.compile(r"overhead[_ -]?reveal|crane[_ -]?reveal|tilt[_ -]?reveal|俯拍.*揭示|俯视.*平视", re.I),
    "orbit": re.compile(r"orbit|环绕|绕拍", re.I),
    "pan_tilt": re.compile(r"\bpan\b|\btilt\b|摇镜|横摇|纵摇", re.I),
    "tracking": re.compile(r"tracking|跟拍|跟随运镜", re.I),
}
CONTINUOUS_FAMILIES = frozenset(MOTION_PATTERNS)


def classify_motion(task: dict[str, Any], prompt: str = "") -> str:
    declared = str((task.get("camera_motion_contract") or {}).get("family") or "").strip().lower()
    if declared in {"fixed", "locked", "static"}:
        return "fixed"
    if declared in CONTINUOUS_FAMILIES:
        return declared
    recipe = task.get("shot_recipe") or {}
    text = " ".join(str(value) for value in (recipe.get("recipe_id"), recipe.get("recipeId"), task.get("camera_policy"), prompt) if value)
    for family, pattern in MOTION_PATTERNS.items():
        if pattern.search(text):
            return family
    return "fixed"


def evaluate_sequence(tasks: list[dict[str, Any]], prompts: dict[str, str] | None = None) -> dict[str, Any]:
    prompts, rows, failures, previous_continuous = prompts or {}, [], [], None
    for index, task in enumerate(tasks):
        key = str(task.get("task_key") or f"task-{index + 1}")
        family = classify_motion(task, prompts.get(key, ""))
        scene = str(task.get("scene_id") or (task.get("prompt_contract") or {}).get("scene_id") or "UNKNOWN")
        duration = float(task.get("duration_seconds") or task.get("duration") or 0.0)
        contract = task.get("camera_motion_contract") or {}
        row = {"task_key": key, "index": index, "scene_id": scene, "family": family, "duration_seconds": duration}
        rows.append(row)
        if family == "oscillation":
            failures.append({"code": "OSCILLATORY_CAMERA_MOTION_FORBIDDEN", "task_key": key})
        if family in CONTINUOUS_FAMILIES:
            required = ("narrative_trigger", "start_composition", "end_composition", "max_motion_seconds")
            missing = [field for field in required if not contract.get(field)]
            if missing:
                failures.append({"code": "CONTINUOUS_CAMERA_MOTION_MISSING_CAUSAL_CONTRACT", "task_key": key, "family": family, "missing": missing})
            elif float(contract["max_motion_seconds"]) > 3.0:
                failures.append({"code": "CONTINUOUS_CAMERA_MOTION_TOO_LONG", "task_key": key})
            if previous_continuous and previous_continuous["scene_id"] == scene:
                failures.append({"code": "ADJACENT_CONTINUOUS_CAMERA_MOTION_REQUIRES_FIXED_COOLDOWN", "task_key": key, "previous_task_key": previous_continuous["task_key"]})
            previous_continuous = row
        else:
            previous_continuous = None
    return {"schema": "qingshan.camera_motion_sequence_gate.v1", "status": "PASS" if not failures else "FAIL", "rows": rows, "failures": failures, "policy": {"dialogue_default": "FIXED_COMPOSITION", "max_adjacent_continuous_motion_shots": 1, "max_single_motion_seconds": 3.0, "oscillatory_camera_motion": "FORBIDDEN"}, "rollback": "Replace only blocked camera clauses; preserve accepted siblings."}
