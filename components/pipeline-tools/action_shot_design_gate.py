#!/usr/bin/env python3
"""Fail closed on overloaded, discontinuous, or repetitive action-shot designs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


ACTION_REQUIRED_FIELDS = (
    "pre_state",
    "actor",
    "action",
    "contact_point",
    "force_direction",
    "force_feedback",
    "result_state",
)


def contract_payload(shot: dict[str, Any]) -> dict[str, Any]:
    """Return the exact design fields that must reach the provider prompt."""
    return {
        "shot_id": shot.get("shot_id"),
        "action_unit": shot.get("action_unit"),
        "visual_tier": shot.get("visual_tier"),
        "information_beats": shot.get("information_beats"),
        "camera": shot.get("camera"),
        "primary_contacts": shot.get("primary_contacts"),
        "result_read_seconds": shot.get("result_read_seconds"),
        "reset_or_replay_allowed": shot.get("reset_or_replay_allowed"),
        "continuity_group": shot.get("continuity_group"),
        "entry_state_token": shot.get("entry_state_token"),
        "exit_state_token": shot.get("exit_state_token"),
    }


def contract_sha256(shot: dict[str, Any]) -> str:
    encoded = json.dumps(
        contract_payload(shot), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prompt_marker(shot: dict[str, Any]) -> str:
    return f"[ACTION_SHOT_CONTRACT_V1:{contract_sha256(shot)}]"


def validate_task_bindings(
    plan: dict[str, Any], tasks: list[dict[str, Any]], root: Path
) -> list[str]:
    """Prove that the structured design was compiled into each provider prompt."""
    failures: list[str] = []
    shots = {str(row.get("shot_id")): row for row in plan.get("shots") or [] if row.get("shot_id")}
    for task in tasks:
        if task.get("tool_type", "video_generation") != "video_generation":
            continue
        task_id = str(task.get("task_key") or task.get("source_id") or "UNKNOWN")
        shot_id = str(task.get("action_design_shot_id") or "")
        if not shot_id or shot_id not in shots:
            failures.append(f"{task_id}:action_design_shot_binding_missing")
            continue
        expected = contract_sha256(shots[shot_id])
        if task.get("action_design_contract_sha256") != expected:
            failures.append(f"{task_id}:action_design_contract_sha256_mismatch")
        prompt_value = task.get("prompt_path") or task.get("prompt_file")
        if not prompt_value:
            failures.append(f"{task_id}:compiled_prompt_path_missing")
            continue
        prompt_path = Path(prompt_value)
        if not prompt_path.is_absolute():
            prompt_path = root / prompt_path
        if not prompt_path.is_file():
            failures.append(f"{task_id}:compiled_prompt_not_found:{prompt_path}")
            continue
        if prompt_marker(shots[shot_id]) not in prompt_path.read_text(encoding="utf-8"):
            failures.append(f"{task_id}:action_design_contract_not_compiled_into_prompt")
    return failures


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def evaluate(plan: dict[str, Any]) -> dict[str, Any]:
    shots = plan.get("shots")
    failures: list[str] = []
    decisions: list[dict[str, Any]] = []
    if not isinstance(shots, list) or not shots:
        shots = []
        failures.append("shots_missing")

    previous_by_group: dict[str, dict[str, Any]] = {}
    camera_families: list[str] = []
    maximum_information_beats = int(plan.get("maximum_information_beats_per_shot", 2))
    maximum_camera_family_share = float(plan.get("maximum_camera_family_share", 0.35))
    maximum_consecutive_camera_family = int(plan.get("maximum_consecutive_camera_family", 2))

    for index, shot in enumerate(shots, 1):
        shot_id = str(shot.get("shot_id") or f"SHOT_{index}")
        shot_failures: list[str] = []
        action_unit = shot.get("action_unit")
        if not isinstance(action_unit, bool):
            shot_failures.append("action_unit_not_explicit")
        information_beats = shot.get("information_beats")
        if not isinstance(information_beats, list) or not information_beats:
            shot_failures.append("information_beats_missing")
        elif len(information_beats) > maximum_information_beats:
            shot_failures.append(
                f"information_load_exceeded:{len(information_beats)}>{maximum_information_beats}"
            )

        camera = shot.get("camera")
        if not isinstance(camera, dict):
            camera = {}
            shot_failures.append("camera_contract_missing")
        family = str(camera.get("family") or "").strip()
        if not family:
            shot_failures.append("camera_family_missing")
        else:
            camera_families.append(family)
        moves = camera.get("moves")
        if not isinstance(moves, list):
            shot_failures.append("camera_moves_not_explicit")
        elif len(moves) > 1:
            shot_failures.append(f"camera_move_budget_exceeded:{len(moves)}>1")

        if action_unit is True:
            if str(shot.get("visual_tier") or "").upper() != "CORE":
                shot_failures.append("action_shot_must_be_core_80")
            for key in ("axis", "screen_direction"):
                if not _text(camera.get(key)):
                    shot_failures.append(f"camera_{key}_missing")
            if camera.get("contact_readable") is not True:
                shot_failures.append("camera_contact_readability_not_locked")

            contracts = shot.get("primary_contacts")
            if not isinstance(contracts, list) or not contracts:
                contracts = []
                shot_failures.append("primary_contact_missing")
            elif len(contracts) > 1:
                shot_failures.append(f"primary_contact_count_exceeded:{len(contracts)}>1")
            for contact_index, contract in enumerate(contracts, 1):
                missing = [key for key in ACTION_REQUIRED_FIELDS if not _text(contract.get(key))]
                if missing:
                    shot_failures.append(
                        f"primary_contact_{contact_index}_fields_missing:{','.join(missing)}"
                    )
            try:
                result_read_seconds = float(shot.get("result_read_seconds"))
            except (TypeError, ValueError):
                shot_failures.append("action_result_read_seconds_missing_or_invalid")
            else:
                if result_read_seconds > 0.8:
                    shot_failures.append("action_result_read_exceeds_0.8s")
                if result_read_seconds <= 0:
                    shot_failures.append("action_result_read_must_be_positive")
            if shot.get("reset_or_replay_allowed") is not False:
                shot_failures.append("reset_or_replay_must_be_explicitly_forbidden")

        group = str(shot.get("continuity_group") or "").strip()
        if group:
            entry = str(shot.get("entry_state_token") or "").strip()
            exit_state = str(shot.get("exit_state_token") or "").strip()
            if not entry or not exit_state:
                shot_failures.append("continuity_state_tokens_missing")
            previous = previous_by_group.get(group)
            if previous and entry != previous["exit_state_token"]:
                shot_failures.append(
                    f"continuity_handoff_mismatch:{previous['shot_id']}:"
                    f"{previous['exit_state_token']}!={entry}"
                )
            previous_by_group[group] = {"shot_id": shot_id, "exit_state_token": exit_state}

        failures.extend(f"{shot_id}:{failure}" for failure in shot_failures)
        decisions.append({
            "shot_id": shot_id,
            "status": "PASS" if not shot_failures else "FAIL",
            "failures": shot_failures,
        })

    if camera_families:
        run_family = camera_families[0]
        run_length = 1
        for family in camera_families[1:]:
            if family == run_family:
                run_length += 1
                if run_length > maximum_consecutive_camera_family:
                    failures.append(
                        f"camera_family_consecutive_exceeded:{family}:"
                        f"{run_length}>{maximum_consecutive_camera_family}"
                    )
            else:
                run_family = family
                run_length = 1
        if len(camera_families) >= 6:
            maximum_count = max(1, math.floor(len(camera_families) * maximum_camera_family_share))
            for family, count in Counter(camera_families).items():
                if count > maximum_count:
                    failures.append(
                        f"camera_family_episode_share_exceeded:{family}:"
                        f"{count}/{len(camera_families)}"
                    )

    return {
        "schema": "backlotos.action_shot_design_gate.v1",
        "episode": plan.get("episode"),
        "status": "PASS" if not failures else "FAIL",
        "fail_closed": True,
        "policy": {
            "one_primary_contact_per_action_shot": True,
            "action_shot_visual_tier": "CORE_80",
            "maximum_information_beats_per_shot": maximum_information_beats,
            "maximum_camera_moves_per_shot": 1,
            "maximum_camera_family_share": maximum_camera_family_share,
            "maximum_consecutive_camera_family": maximum_consecutive_camera_family,
            "maximum_action_result_read_seconds": 0.8,
            "cross_shot_state_token_match_required": True,
        },
        "shot_count": len(shots),
        "decisions": decisions,
        "camera_family_counts": dict(Counter(camera_families)),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.plan.read_text(encoding="utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "failures": len(result["failures"]),
        "out": str(args.out),
    }, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
