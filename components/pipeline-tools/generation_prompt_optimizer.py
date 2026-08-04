#!/usr/bin/env python3
"""Deterministically compile structured generation contracts into prompts."""

from __future__ import annotations

import hashlib
from typing import Any


BEGIN = "【自动优化契约开始】"
END = "【自动优化契约结束】"


def _without_previous_block(prompt: str) -> str:
    if BEGIN not in prompt:
        return prompt.rstrip()
    before, remainder = prompt.split(BEGIN, 1)
    if END not in remainder:
        return before.rstrip()
    _, after = remainder.split(END, 1)
    return (before.rstrip() + "\n" + after.lstrip()).rstrip()


def _percent(value: Any) -> int:
    return round(float(value) * 100)


def _action_signature(task: dict[str, Any]) -> str:
    beats = (task.get("performance_spec") or {}).get("motion_beats") or []
    if not beats:
        return ""
    beat = beats[0]
    return "|".join(str(beat.get(key) or "").strip() for key in ("subject", "action", "contact_point", "direction", "end_state"))


def optimize_prompt(task: dict[str, Any], prompt: str, prior_tasks: list[dict[str, Any]] | None = None) -> tuple[str, dict[str, Any]]:
    """Return an idempotently optimized prompt and auditable rule receipt."""
    base = _without_previous_block(prompt)
    clauses: list[str] = []
    applied_rules: list[str] = []
    prior_tasks = prior_tasks or []

    tempo = task.get("performance_tempo_contract") or {}
    if tempo:
        complete_by = tempo.get("primary_action_complete_by_seconds")
        hold = tempo.get("result_hold_seconds")
        clauses.append(
            f"【PF-004实时动作】动作以REAL_TIME_1X完成，主接触最迟在{complete_by}秒完成，"
            f"终态只读{hold}秒；不得慢放、复位、重演或靠运镜填时长。"
        )
        applied_rules.append("PF-004")

    sequence = task.get("action_sequence_contract") or {}
    if sequence:
        clauses.append(
            "【PF-008/PF-009因果交接】首帧严格为入口状态"
            f"{sequence.get('entry_state_token')}；只完成一个主接触；尾帧严格落在"
            f"{sequence.get('exit_state_token')}，且可直接作为下一镜首帧，不得复位或偷跑下一事件。"
        )
        applied_rules.extend(["PF-008", "PF-009"])

    ownership = task.get("action_actor_ownership_contract") or {}
    if ownership:
        forbidden = "、".join(ownership.get("forbidden_foreground_actions") or [])
        clauses.append(
            f"【PF-010能力归属】唯一动作所有者为{ownership.get('ability_owner')}；"
            f"继承前景人物{ownership.get('inherited_foreground_actor')}不得{forbidden}；"
            "特效必须从所有者可见接触点起始。"
        )
        applied_rules.append("PF-010")

    spatial = task.get("action_spatial_feasibility_contract") or {}
    if spatial:
        corridor = spatial["collision_corridor"]
        effect = spatial["effect_geometry"]
        effect_label = str(effect.get("label") or "动作主体")
        clauses.append(
            "【PF-011首尾帧动作空间】开放碰撞通道为画幅"
            f"横向{_percent(corridor['x_min'])}%至{_percent(corridor['x_max'])}%、"
            f"纵向{_percent(corridor['y_min'])}%至{_percent(corridor['y_max'])}%；"
            "保护道具和非接触肢体不得进入通道。"
            f"特效位于{effect.get('depth_order')}深度层，平面方向{effect.get('plane_orientation')}，"
            f"{effect_label}宽不超过画幅{_percent(effect['max_width_ratio'])}%，"
            f"{effect_label}高不超过画幅{_percent(effect['max_height_ratio'])}%，"
            f"人物遮挡不超过{_percent(spatial['maximum_subject_occlusion_ratio'])}%。"
            "先发生唯一身体接触，再出现裂纹、白汽或其他反馈；"
            "尾帧保留保护道具、明确人物落点，并保持下一镜可执行姿态。"
        )
        applied_rules.append("PF-011")
    prior_action_tasks = [row for row in prior_tasks if row.get("action_sequence_contract")]
    if task.get("action_sequence_contract") and prior_action_tasks:
        completed = [
            str((row.get("action_sequence_contract") or {}).get("exit_state_token") or "")
            for row in prior_action_tasks
        ]
        clauses.append(
            "【PF-012历史动作去重】已完成的关联动作画面为："
            + "、".join(completed)
            + "。本镜不得重演这些接触、反馈或终态，只能从最近尾帧继续当前唯一动作。"
        )
        applied_rules.append("PF-012")

    optimized = base
    if clauses:
        optimized += "\n" + BEGIN + "\n" + "\n".join(clauses) + "\n" + END + "\n"
    before_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    after_sha = hashlib.sha256(optimized.encode("utf-8")).hexdigest()
    return optimized, {
        "schema": "qingshan.generation_prompt_optimizer_receipt.v1",
        "task_key": task.get("task_key"),
        "status": "PASS",
        "applied_failure_memory_rules": list(dict.fromkeys(applied_rules)),
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        "changed": before_sha != after_sha,
        "idempotent_block": True,
        "prior_action_task_keys": [row.get("task_key") for row in prior_action_tasks],
        "action_signature": _action_signature(task),
    }


def validate_batch(tasks: list[dict[str, Any]], prompts: dict[str, str]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    seen_signatures: dict[str, str] = {}
    prior_action_keys: list[str] = []
    for task in tasks:
        if task.get("prompt_optimizer_required") is not True:
            continue
        key = str(task.get("task_key") or task.get("source_id") or "unknown")
        receipt = task.get("prompt_optimizer_receipt") or {}
        prompt = prompts.get(key, "")
        actual_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if receipt.get("status") != "PASS":
            failures.append({"task_key": key, "code": "PROMPT_OPTIMIZER_NOT_RUN"})
        if receipt.get("after_sha256") != actual_sha:
            failures.append({"task_key": key, "code": "OPTIMIZED_PROMPT_SHA_MISMATCH"})
        expected = {"PF-004", "PF-008", "PF-009"} if task.get("action_sequence_contract") else set()
        if task.get("action_actor_ownership_contract"):
            expected.add("PF-010")
        if task.get("action_spatial_feasibility_contract"):
            expected.add("PF-011")
        if task.get("action_sequence_contract") and prior_action_keys:
            expected.add("PF-012")
        actual = set(receipt.get("applied_failure_memory_rules") or [])
        if not expected.issubset(actual):
            failures.append({"task_key": key, "code": "REQUIRED_OPTIMIZATION_RULE_MISSING"})
        if expected and (BEGIN not in prompt or END not in prompt):
            failures.append({"task_key": key, "code": "OPTIMIZED_CONTRACT_BLOCK_MISSING"})
        signature = _action_signature(task)
        if signature and signature in seen_signatures:
            failures.append({"task_key": key, "code": "ACTION_VISUAL_DUPLICATES_PRIOR_SHOT"})
        if signature:
            seen_signatures[signature] = key
        if task.get("action_sequence_contract"):
            if receipt.get("prior_action_task_keys") != prior_action_keys:
                failures.append({"task_key": key, "code": "PRIOR_ACTION_PROMPTS_NOT_FULLY_READ"})
            prior_action_keys.append(key)
    return {
        "schema": "qingshan.generation_prompt_optimizer_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "fail_closed": True,
        "failures": failures,
    }
