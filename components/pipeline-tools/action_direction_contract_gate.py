#!/usr/bin/env python3
"""Reject internally contradictory lateral action and contact contracts."""

from __future__ import annotations
from typing import Any

_LATERAL = {"RIGHT_TO_LEFT": ("SCREEN_RIGHT", "SCREEN_LEFT"), "LEFT_TO_RIGHT": ("SCREEN_LEFT", "SCREEN_RIGHT")}
_OPPOSITE = {"RIGHT_TO_LEFT": "LEFT_TO_RIGHT", "LEFT_TO_RIGHT": "RIGHT_TO_LEFT"}


def evaluate_batch(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    failures, rows = [], []
    for task in (item for item in tasks if item.get("action_unit")):
        key = str(task.get("task_key") or "unknown")
        contract = task.get("action_direction_contract") or {}
        if not contract:
            failures.append({"code": "ACTION_DIRECTION_CONTRACT_MISSING", "task_key": key})
            continue
        entry_side = str(contract.get("entry_screen_side") or "")
        travel = str(contract.get("travel_direction") or "")
        recoil = str(contract.get("recoil_direction") or "")
        terminal_side = str(contract.get("terminal_screen_side") or "")
        body_part = str(contract.get("contact_body_part") or "")
        target = str(contract.get("contact_target") or "")
        rows.append({"task_key": key, "entry_screen_side": entry_side, "travel_direction": travel, "recoil_direction": recoil, "terminal_screen_side": terminal_side, "contact_body_part": body_part, "contact_target": target})
        required = {"entry_screen_side": entry_side, "travel_direction": travel, "terminal_screen_side": terminal_side, "contact_body_part": body_part, "contact_target": target}
        missing = [name for name, value in required.items() if not value]
        if missing:
            failures.append({"code": "ACTION_DIRECTION_FIELD_MISSING", "task_key": key, "fields": missing})
            continue
        if travel in _LATERAL:
            expected_entry, _ = _LATERAL[travel]
            if entry_side != expected_entry:
                failures.append({"code": "TRAVEL_DIRECTION_ENTRY_SIDE_CONTRADICTION", "task_key": key, "expected": expected_entry, "actual": entry_side})
            if recoil:
                if recoil != _OPPOSITE[travel]:
                    failures.append({"code": "RECOIL_DIRECTION_NOT_OPPOSITE_TRAVEL", "task_key": key, "expected": _OPPOSITE[travel], "actual": recoil})
                if terminal_side != entry_side:
                    failures.append({"code": "RECOIL_TERMINAL_SIDE_CONTRADICTION", "task_key": key, "expected": entry_side, "actual": terminal_side})
    return {"schema": "qingshan.action_direction_contract_gate.v1", "status": "PASS" if not failures else "FAIL", "rows": rows, "failures": failures, "policy": "Compile action prompts from explicit direction and contact contracts."}
