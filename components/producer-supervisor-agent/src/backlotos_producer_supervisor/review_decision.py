"""Turn a review report + fast-pacing checklist into a PASS/ADVISE/BLOCK
decision plus structured revision requests. This module NEVER rewrites
prose -- it only proposes structured revision task items for the Story
Agent, and never silently downgrades a BLOCK-severity issue to PASS.
"""
from __future__ import annotations

from typing import Any

BLOCKING_SEVERITIES = {"BLOCK", "BLOCKING", "CRITICAL"}

CHECKLIST_ITEMS = (
    "early_conflict",
    "every_scene_advances",
    "no_recap_or_filler",
    "escalating_tension",
    "consequential_end_hook",
    "no_padding_for_duration",
)


def _issue_is_blocking(issue: dict) -> bool:
    if issue.get("blocking") is True:
        return True
    severity = str(issue.get("severity", "")).upper()
    return severity in BLOCKING_SEVERITIES


def review_decision(review_report: dict, checklist: dict | None = None) -> dict:
    issues = review_report.get("issues") or []
    blocking_issues = [i for i in issues if _issue_is_blocking(i)]
    non_blocking_issues = [i for i in issues if not _issue_is_blocking(i)]

    checklist = checklist or {}
    checklist_failures = [item for item in CHECKLIST_ITEMS if item in checklist and checklist.get(item) is False]
    checklist_not_run = [item for item in CHECKLIST_ITEMS if item not in checklist]

    reasons: list[str] = []
    revision_requests = []
    for issue in blocking_issues:
        reasons.append(f"BLOCKING issue {issue.get('issue_id', issue.get('shot_id', 'unknown'))}: {issue.get('problem', issue.get('description', 'unspecified'))}")
        revision_requests.append({
            "issue_id": issue.get("issue_id"),
            "scene_id": issue.get("scene_id"),
            "shot_id": issue.get("shot_id"),
            "problem": issue.get("problem", issue.get("description")),
            "requested_change": issue.get("requested_change", "revise to resolve blocking issue"),
        })
    for item in checklist_failures:
        reasons.append(f"pacing checklist failed: {item}")
        revision_requests.append({"issue_id": f"CHECKLIST_{item}", "problem": f"checklist item '{item}' failed", "requested_change": f"address {item} per US premium-streaming pacing standard"})

    if blocking_issues:
        decision = "BLOCK"
    elif non_blocking_issues or checklist_failures:
        decision = "ADVISE"
        for issue in non_blocking_issues:
            reasons.append(f"advisory issue {issue.get('issue_id', 'unknown')}: {issue.get('problem', issue.get('description', ''))}")
            revision_requests.append({
                "issue_id": issue.get("issue_id"), "scene_id": issue.get("scene_id"), "shot_id": issue.get("shot_id"),
                "problem": issue.get("problem", issue.get("description")),
                "requested_change": issue.get("requested_change", "consider revising"),
            })
    elif checklist_not_run:
        decision = "ADVISE"
        reasons.append("pacing checklist was not fully executed")
    else:
        decision = "PASS"

    return {
        "ok": True,
        "decision": decision,
        "reasons": reasons,
        "structured_revision_requests": revision_requests,
        "evidence_refs": review_report.get("evidence_refs", []),
        "checklist_not_run": checklist_not_run,
        "note": "this verb never rewrites prose; it only proposes structured revision items and a stage-gate decision",
    }
