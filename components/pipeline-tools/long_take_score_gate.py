#!/usr/bin/env python3
"""Apply the 60-point long-take admission rule with hard-fact overrides."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


THRESHOLD = 60
HARD_FAILURES = {
    "IDENTITY", "SAFETY", "ERA", "OCR", "MEDIA_INTEGRITY",
    "COMBAT_IDENTITY_OUTCOME", "VISIBLE_ACTOR_FREEZE",
}


def adjudicate(
    score: float,
    hard_failures: list[str] | None = None,
    *,
    visible_actor_count: int = 1,
    visible_actor_motion_score: float | None = None,
    combat_identity_outcome_score: float | None = None,
) -> dict:
    hard = sorted(set(hard_failures or []))
    unknown = sorted(set(hard) - HARD_FAILURES)
    if unknown:
        raise ValueError(f"unsupported hard failures: {', '.join(unknown)}")
    if visible_actor_count < 1:
        raise ValueError("visible_actor_count must be at least 1")
    if visible_actor_count > 1 and visible_actor_motion_score is None:
        raise ValueError("multi-actor long take requires visible_actor_motion_score")
    if visible_actor_motion_score is not None and not 0 <= visible_actor_motion_score <= 100:
        raise ValueError("visible_actor_motion_score must be between 0 and 100")
    motion_passed = visible_actor_count == 1 or visible_actor_motion_score >= THRESHOLD
    if combat_identity_outcome_score is not None and not 0 <= combat_identity_outcome_score <= 100:
        raise ValueError("combat_identity_outcome_score must be between 0 and 100")
    combat_passed = combat_identity_outcome_score is None or combat_identity_outcome_score >= THRESHOLD
    passed = score >= THRESHOLD and motion_passed and combat_passed and not hard
    return {
        "schema": "backlotos.long_take_score_gate.v1",
        "score_100": score, "minimum_score_100": THRESHOLD,
        "hard_failures": hard, "hard_failures_override_score": True,
        "visible_actor_count": visible_actor_count,
        "visible_actor_motion_score_100": visible_actor_motion_score,
        "visible_actor_motion_minimum_100": THRESHOLD if visible_actor_count > 1 else None,
        "visible_actor_motion_decision": "PASS" if motion_passed else "FAIL",
        "combat_identity_outcome_score_100": combat_identity_outcome_score,
        "combat_identity_outcome_minimum_100": THRESHOLD if combat_identity_outcome_score is not None else None,
        "combat_identity_outcome_decision": "PASS" if combat_passed else "FAIL",
        "decision": "PASS" if passed else "FAIL",
        "paid_regeneration_allowed": not passed,
        "at_threshold_retained": score == THRESHOLD and not hard,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--score", type=float, required=True)
    parser.add_argument("--hard-failure", action="append", default=[])
    parser.add_argument("--visible-actor-count", type=int, default=1)
    parser.add_argument("--visible-actor-motion-score", type=float)
    parser.add_argument("--combat-identity-outcome-score", type=float)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = adjudicate(
        args.score, args.hard_failure,
        visible_actor_count=args.visible_actor_count,
        visible_actor_motion_score=args.visible_actor_motion_score,
        combat_identity_outcome_score=args.combat_identity_outcome_score,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
