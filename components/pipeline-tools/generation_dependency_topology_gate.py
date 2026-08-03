#!/usr/bin/env python3
"""Keep only continuity-critical shot chains serial while siblings stay parallel."""

from __future__ import annotations
from typing import Any

PARALLEL = "INDEPENDENT_PARALLEL"
CHAINED = "TAIL_CHAINED_SERIAL"


def evaluate_batch(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    failures, rows = [], []
    keys = {str(task.get("task_key")) for task in tasks if task.get("task_key")}
    for task in tasks:
        key = str(task.get("task_key") or "UNKNOWN")
        mode = str(task.get("generation_schedule_mode") or PARALLEL)
        dependency = task.get("depends_on_task")
        contract = task.get("action_sequence_contract") or {}
        rows.append({"task_key": key, "mode": mode, "depends_on_task": dependency})
        if mode not in {PARALLEL, CHAINED}:
            failures.append({"code": "UNKNOWN_GENERATION_SCHEDULE_MODE", "task_key": key, "mode": mode})
        elif mode == PARALLEL and dependency:
            failures.append({"code": "INDEPENDENT_SHOT_INCORRECTLY_SERIALIZED", "task_key": key, "depends_on_task": dependency})
        elif mode == CHAINED:
            sequence_index = int(contract.get("sequence_index") or 0)
            if sequence_index > 1 and not dependency:
                failures.append({"code": "CHAINED_SHOT_PREDECESSOR_MISSING", "task_key": key})
            if dependency and str(dependency) not in keys:
                failures.append({"code": "CHAINED_SHOT_PREDECESSOR_UNKNOWN", "task_key": key, "depends_on_task": dependency})
            if sequence_index > 1 and not contract.get("predecessor_tail_frame_ref"):
                failures.append({"code": "CHAINED_SHOT_TAIL_FRAME_DESTINATION_MISSING", "task_key": key})
            if sequence_index > 1 and task.get("dependencies_ready") is not False:
                failures.append({"code": "CHAINED_SHOT_PREMATURELY_READY", "task_key": key})
    return {"schema": "qingshan.generation_dependency_topology_gate.v1", "status": "PASS" if not failures else "FAIL", "rows": rows, "failures": failures, "policy": {"independent_shots": "concurrent", "continuity_chains": "serial within chain", "episode_batch_barrier": False}}
