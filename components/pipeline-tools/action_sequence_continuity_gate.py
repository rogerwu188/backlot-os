#!/usr/bin/env python3
"""Reject hidden events between adjacent continuity-critical action shots."""

from __future__ import annotations
from typing import Any


def evaluate_batch(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    actions = [task for task in tasks if task.get("action_unit")]
    failures, rows, previous = [], [], None
    for index, task in enumerate(actions):
        key = str(task.get("task_key") or f"action-{index + 1}")
        contract = task.get("action_sequence_contract") or {}
        entry = str(contract.get("entry_state_token") or "")
        exit_state = str(contract.get("exit_state_token") or "")
        row = {"task_key": key, "sequence_index": index, "entry_state_token": entry, "exit_state_token": exit_state}
        rows.append(row)
        if not entry or not exit_state:
            failures.append({"code": "ACTION_BOUNDARY_STATE_MISSING", "task_key": key})
        if len((task.get("performance_spec") or {}).get("motion_beats") or []) != 1:
            failures.append({"code": "ACTION_UNIT_MUST_HAVE_EXACTLY_ONE_PRIMARY_CONTACT", "task_key": key})
        if previous:
            if entry != previous["exit_state_token"]:
                failures.append({"code": "HIDDEN_EVENT_BETWEEN_ACTION_SHOTS", "previous_task_key": previous["task_key"], "task_key": key, "previous_exit_state": previous["exit_state_token"], "current_entry_state": entry})
            if task.get("depends_on_task") != previous["task_key"]:
                failures.append({"code": "ACTION_SHOT_PREDECESSOR_DEPENDENCY_MISSING", "task_key": key, "expected": previous["task_key"]})
            if not contract.get("predecessor_tail_frame_ref"):
                failures.append({"code": "PREDECESSOR_TAIL_FRAME_BINDING_MISSING", "task_key": key})
        previous = row
    return {"schema": "qingshan.action_sequence_continuity_gate.v1", "status": "PASS" if not failures else "FAIL", "rows": rows, "failures": failures, "policy": "Previous accepted tail state equals the next entry exactly; every intervening event is its own generated unit."}
