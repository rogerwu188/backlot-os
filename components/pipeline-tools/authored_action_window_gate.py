#!/usr/bin/env python3
"""Require assembly to preserve only the authored real-time action window."""

from __future__ import annotations
from typing import Any


def evaluate_batch(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    rows, failures = [], []
    for task in tasks:
        if not task.get("action_unit"):
            continue
        key = str(task.get("task_key") or "UNKNOWN")
        tempo = task.get("performance_tempo_contract") or {}
        contract = task.get("assembly_window_contract") or {}
        row = {"task_key": key, "contract": contract}
        rows.append(row)
        if not contract:
            failures.append({"code": "ACTION_ASSEMBLY_WINDOW_CONTRACT_MISSING", "task_key": key})
            continue

        start = float(contract.get("trim_start_seconds") or 0.0)
        end = float(contract.get("trim_end_seconds") or 0.0)
        action_end = float(tempo.get("primary_action_complete_by_seconds") or 0.0)
        result_hold = float(tempo.get("result_hold_seconds") or 0.0)
        authored_end = action_end + result_hold
        provider_duration = float(task.get("duration_seconds") or task.get("duration") or 0.0)
        row.update({
            "trim_start_seconds": start,
            "trim_end_seconds": end,
            "authored_end_seconds": authored_end,
            "provider_duration_seconds": provider_duration,
        })

        if start < 0.0 or end <= start:
            failures.append({"code": "ACTION_ASSEMBLY_WINDOW_INVALID", "task_key": key})
        if end > authored_end + 0.25:
            failures.append({
                "code": "ACTION_ASSEMBLY_EXCEEDS_AUTHORED_WINDOW",
                "task_key": key,
                "trim_end_seconds": end,
                "maximum_seconds": authored_end + 0.25,
            })
        if end - start > 2.5:
            failures.append({"code": "ACTION_ASSEMBLY_WINDOW_TOO_LONG", "task_key": key, "window_seconds": end - start})
        if contract.get("preserve_native_speed") is not True:
            failures.append({"code": "ACTION_ASSEMBLY_SPEED_CHANGE_FORBIDDEN", "task_key": key})
        if contract.get("duplicate_hold_policy") != "DROP_ONLY_DUPLICATE_TAIL_FRAMES":
            failures.append({"code": "ACTION_DUPLICATE_TAIL_POLICY_INVALID", "task_key": key})
        if provider_duration > end and contract.get("provider_tail_disposition") != "DISCARD_UNAUTHORED_TAIL":
            failures.append({"code": "UNAUTHORED_PROVIDER_TAIL_NOT_DISCARDED", "task_key": key})

    return {
        "schema": "backlotos.authored-action-window-gate/1.0",
        "status": "PASS" if not failures else "FAIL",
        "rows": rows,
        "failures": failures,
        "policy": {
            "playback": "PRESERVE_NATIVE_REAL_TIME",
            "maximum_action_window_seconds": 2.5,
            "provider_minimum_duration_tail": "DISCARD_UNAUTHORED_TAIL",
            "duplicate_frames": "DROP_ONLY_DUPLICATE_TAIL_FRAMES",
        },
    }
