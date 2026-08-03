#!/usr/bin/env python3
"""Require explicit actor ownership when a chained shot changes action owner."""

from __future__ import annotations

from typing import Any


_GENERIC_SUBJECTS = {"", "本镜动作主体", "subject", "actor", "character"}


def evaluate_batch(tasks: list[dict[str, Any]], prompts: dict[str, str] | None = None) -> dict[str, Any]:
    prompts = prompts or {}
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for task in (item for item in tasks if item.get("action_unit")):
        key = str(task.get("task_key") or "unknown")
        beats = (task.get("performance_spec") or {}).get("motion_beats") or []
        generic = [index for index, beat in enumerate(beats) if str(beat.get("subject") or "").strip().lower() in _GENERIC_SUBJECTS]
        if generic:
            failures.append({"code": "ACTION_SUBJECT_GENERIC", "task_key": key, "beat_indexes": generic})
        required = bool(task.get("requires_actor_ownership_lock"))
        contract = task.get("action_actor_ownership_contract") or {}
        rows.append({"task_key": key, "required": required, "ability_owner": contract.get("ability_owner"), "inherited_foreground_actor": contract.get("inherited_foreground_actor")})
        if not required:
            continue
        fields = ("ability_owner", "inherited_foreground_actor", "forbidden_foreground_actions", "required_prompt_clauses")
        missing = [field for field in fields if not contract.get(field)]
        if contract.get("visible_origin_required") is not True:
            missing.append("visible_origin_required")
        if missing:
            failures.append({"code": "ACTOR_OWNERSHIP_CONTRACT_INCOMPLETE", "task_key": key, "fields": missing})
            continue
        if str(contract["ability_owner"]) == str(contract["inherited_foreground_actor"]):
            failures.append({"code": "OWNER_CHANGE_LOCK_WITHOUT_ACTOR_CHANGE", "task_key": key})
        prompt = prompts.get(key, "")
        absent = [clause for clause in contract["required_prompt_clauses"] if str(clause) not in prompt]
        if absent:
            failures.append({"code": "ACTOR_OWNERSHIP_PROMPT_CLAUSE_MISSING", "task_key": key, "clauses": absent})
    return {
        "schema": "qingshan.action_actor_ownership_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "rows": rows,
        "failures": failures,
        "policy": "A tail-chained shot that changes the action owner must name the inherited foreground actor, sole ability owner, forbidden foreground actions, and visible effect origin in structured data and the provider prompt.",
    }
