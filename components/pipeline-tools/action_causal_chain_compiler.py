#!/usr/bin/env python3
"""Compile action beats into one-phase, exact-tail generation tasks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def compile_chain(plan: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    tasks: list[dict[str, Any]] = []
    previous_key: str | None = None
    previous_exit: str | None = None
    for index, beat in enumerate(plan.get("beats") or [], start=1):
        key = str(beat.get("task_key") or f"ACTION-{index:02d}")
        phases = beat.get("visible_phases") or []
        if len(phases) != 1:
            failures.append({"task_key": key, "code": "EXACTLY_ONE_VISIBLE_PHASE_REQUIRED"})
        if index > 1 and beat.get("entry_state_token") != previous_exit:
            failures.append({"task_key": key, "code": "ENTRY_DOES_NOT_MATCH_PREDECESSOR_EXIT"})
        prop = beat.get("prop_function") or {}
        if prop and not prop.get("required_function_class"):
            failures.append({"task_key": key, "code": "PROP_FUNCTION_CLASS_REQUIRED"})
        if beat.get("real_time_1x") is not True:
            failures.append({"task_key": key, "code": "REAL_TIME_1X_REQUIRED"})
        task = {
            **beat,
            "sequence_index": index,
            "generation_schedule_mode": "TAIL_CHAINED_SERIAL",
            "depends_on_task": previous_key,
            "tail_to_head_identity_required": index > 1,
            "exact_predecessor_tail_required": index > 1,
            "model": beat.get("model", plan.get("model", "seedance-2.0-pro")),
            "resolution": beat.get("resolution", plan.get("resolution", "1080p")),
            "provider_duration_seconds": beat.get("provider_duration_seconds", 4),
            "edit_policy": "TRIM_ONLY_NO_SPEED_CHANGE",
            "camera_policy": "FIXED_AXIS_NO_SWAY_UNLESS_SCRIPT_MOTIVATED",
            "prompt_optimizer_required": True,
            "pre_generation_gates": [
                "PROP_FUNCTION_CLASS",
                "ONE_VISIBLE_CAUSAL_PHASE",
                "RELATIONAL_PHYSICAL_SCALE",
                "REAL_TIME_1X",
                "EXACT_PREDECESSOR_TAIL",
                "PRIOR_RELATED_ACTION_PROMPT_DEDUP",
                "NON_INTERSECTING_MOVEMENT_LANES",
            ],
        }
        task["compiled_contract_sha256"] = sha256_text(json.dumps(task, ensure_ascii=False, sort_keys=True))
        tasks.append(task)
        previous_key = key
        previous_exit = beat.get("exit_state_token")
    return {
        "schema": "qingshan.action_causal_chain.v1",
        "status": "PASS" if tasks and not failures else "FAIL",
        "fail_closed": True,
        "chain_id": plan.get("chain_id"),
        "global_scheduling_policy": {"this_chain": "SERIAL_EXACT_TAIL", "unrelated_generation_and_qa": "PARALLEL"},
        "tasks": tasks,
        "failures": failures,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = compile_chain(json.loads(args.plan.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": result["status"], "tasks": len(result["tasks"]), "failures": result["failures"]}, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
