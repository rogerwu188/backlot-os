#!/usr/bin/env python3
"""Prevent atomic actions from being stretched into model-generated slow motion."""

from __future__ import annotations
from typing import Any


def evaluate_batch(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    rows, failures = [], []
    for task in tasks:
        if not task.get("action_unit"):
            continue
        key = str(task.get("task_key") or "UNKNOWN")
        duration = float(task.get("duration_seconds") or task.get("duration") or 0.0)
        contract = task.get("performance_tempo_contract") or {}
        rows.append({"task_key": key, "duration_seconds": duration, "contract": contract})
        if not contract:
            failures.append({"code": "ACTION_TEMPO_CONTRACT_MISSING", "task_key": key})
            continue
        if contract.get("playback_speed") != "REAL_TIME_1X":
            failures.append({"code": "ACTION_NOT_AUTHORED_AT_REAL_TIME", "task_key": key})
        max_action = float(contract.get("primary_action_complete_by_seconds") or 0.0)
        if max_action <= 0.0 or max_action > 2.0:
            failures.append({"code": "ATOMIC_ACTION_COMPLETION_WINDOW_INVALID", "task_key": key, "actual_seconds": max_action, "maximum_seconds": 2.0})
        if duration > 4.0:
            failures.append({"code": "ATOMIC_ACTION_DURATION_INVITES_SLOW_MOTION", "task_key": key, "actual_seconds": duration, "maximum_seconds": 4.0})
        if float(contract.get("result_hold_seconds") or 0.0) > 0.75:
            failures.append({"code": "ACTION_RESULT_HOLD_TOO_LONG", "task_key": key})
    return {"schema": "qingshan.performance_tempo_gate.v1", "status": "PASS" if not failures else "FAIL", "rows": rows, "failures": failures, "policy": "Atomic contact completes within 2.0s at real-time 1x; total unit <=4.0s; result hold 0.45-0.75s."}
