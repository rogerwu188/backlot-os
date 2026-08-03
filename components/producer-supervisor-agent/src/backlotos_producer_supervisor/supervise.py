"""Cross-stage evidence consistency supervision for one episode.

Never reports an unexecuted check as PASS. Checks that cannot run (missing
inputs, unreadable files) report NOT_RUN, not PASS.
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from .ledger import is_hex64, sha256_hex


def _check_identity(evidence: list[dict], episode_id: str, project_id: str | None, current_version: int | None) -> dict:
    if not evidence:
        return {"status": "NOT_RUN", "reason": "no evidence supplied", "mismatches": [], "stale_by_version": []}
    mismatches = []
    stale = []
    for item in evidence:
        ref = item.get("ref", item.get("stage", "unknown"))
        if item.get("episode_id") != episode_id:
            mismatches.append({"ref": ref, "reason": "episode_id_mismatch", "found": item.get("episode_id")})
        if project_id is not None and item.get("project_id") != project_id:
            mismatches.append({"ref": ref, "reason": "project_id_mismatch", "found": item.get("project_id")})
        if current_version is not None:
            if item.get("version") is None:
                stale.append({"ref": ref, "reason": "version_missing", "current_version": current_version})
            elif item.get("version") != current_version:
                stale.append({"ref": ref, "reason": "version_mismatch", "evidence_version": item.get("version"), "current_version": current_version})
    return {"status": "FAIL" if mismatches or stale else "PASS", "mismatches": mismatches, "stale_by_version": stale}


def _check_sha(evidence: list[dict]) -> dict:
    malformed = []
    verified = []
    not_run = []
    for item in evidence:
        ref = item.get("ref", item.get("stage", "unknown"))
        sha = item.get("sha256")
        if sha is not None and not is_hex64(sha):
            malformed.append({"ref": ref, "sha256": sha})
            continue
        file_path = item.get("local_path")
        if sha and file_path and Path(file_path).is_file():
            actual = sha256_hex(Path(file_path).read_bytes())
            if actual != sha:
                malformed.append({"ref": ref, "reason": "sha256_does_not_match_file", "declared": sha, "actual": actual})
            else:
                verified.append(ref)
        else:
            not_run.append({"ref": ref, "reason": "no_local_path_or_no_sha_to_verify"})
    status = "FAIL" if malformed else ("PASS" if verified else "NOT_RUN")
    return {"status": status, "malformed": malformed, "verified": verified, "not_run": not_run}


def _check_stale_timestamps(evidence: list[dict], latest_accepted_revision_at: str | None) -> dict:
    if not latest_accepted_revision_at:
        return {"status": "NOT_RUN", "reason": "no latest_accepted_revision_at supplied", "stale": []}
    stale = [
        {"ref": item.get("ref", item.get("stage", "unknown")), "timestamp": item.get("timestamp")}
        for item in evidence
        if item.get("timestamp") and item["timestamp"] < latest_accepted_revision_at
    ]
    return {"status": "FAIL" if stale else "PASS", "stale": stale}


def _check_duration(evidence: list[dict], target_duration_seconds: float | None) -> dict:
    if target_duration_seconds is None:
        return {"status": "NOT_RUN", "reason": "no target_duration_seconds supplied"}
    duration_items = [item for item in evidence if isinstance(item.get("duration_seconds"), (int, float))]
    if not duration_items:
        return {"status": "NOT_RUN", "reason": "no evidence item reported duration_seconds"}
    final_items = [
        item for item in duration_items
        if item.get("duration_scope") in {"final", "episode"}
        or item.get("scope") in {"final", "final_cut", "episode"}
        or item.get("stage") in {"final_candidate", "final_review"}
    ]
    if final_items:
        # Multiple final measurements must agree; summing them would double
        # count the same episode across review stages.
        values = [float(item["duration_seconds"]) for item in final_items]
        if max(values) - min(values) > 0.25:
            return {"status": "FAIL", "reason": "conflicting final duration evidence", "values": values}
        total = values[-1]
        measurement = "final_media"
    elif len(duration_items) == 1:
        total = float(duration_items[0]["duration_seconds"])
        measurement = "single_evidence"
    elif all(item.get("duration_scope") in {"shot", "segment"} or item.get("scope") in {"shot", "segment"} for item in duration_items):
        total = sum(float(item["duration_seconds"]) for item in duration_items)
        measurement = "summed_segments"
    else:
        return {"status": "NOT_RUN", "reason": "multiple duration values lack final/segment scope; refusing to double count"}
    tolerance = max(2.0, target_duration_seconds * 0.05)
    ok = abs(total - target_duration_seconds) <= tolerance
    return {"status": "PASS" if ok else "FAIL", "measurement": measurement, "total_duration_seconds": round(total, 2), "target_duration_seconds": target_duration_seconds, "tolerance": tolerance}


def _check_padding(evidence: list[dict], threshold: float = 0.9) -> dict:
    texts = [item.get("text") for item in evidence if isinstance(item.get("text"), str) and item.get("text").strip()]
    if len(texts) < 2:
        return {"status": "NOT_RUN", "reason": "fewer than 2 text-bearing evidence items", "flags": []}
    flags = []
    for i in range(1, len(texts)):
        ratio = difflib.SequenceMatcher(None, texts[i - 1], texts[i]).ratio()
        if ratio >= threshold:
            flags.append({"index": i, "similarity_ratio": round(ratio, 3)})
    return {"status": "ADVISE" if flags else "PASS", "flags": flags, "note": "advisory only; supervisor does not rewrite scripts"}


def supervise_episode(
    episode_id: str,
    evidence: list[dict],
    *,
    project_id: str | None = None,
    current_version: int | None = None,
    latest_accepted_revision_at: str | None = None,
    target_duration_seconds: float | None = None,
) -> dict:
    identity = _check_identity(evidence, episode_id, project_id, current_version)
    sha_check = _check_sha(evidence)
    stale_check = _check_stale_timestamps(evidence, latest_accepted_revision_at)
    duration_check = _check_duration(evidence, target_duration_seconds)
    padding_check = _check_padding(evidence)

    stale_flag = "STALE_EVIDENCE" if (identity["stale_by_version"] or stale_check["status"] == "FAIL") else None
    checks = [identity, sha_check, stale_check, duration_check]
    hard_fail = any(check["status"] == "FAIL" for check in checks)
    incomplete = any(check["status"] == "NOT_RUN" for check in checks)
    overall = "FAIL" if hard_fail else ("NOT_RUN" if incomplete else ("ADVISE" if padding_check["status"] == "ADVISE" else "PASS"))

    return {
        "ok": overall in {"PASS", "ADVISE"},
        "status": overall,
        "episode_id": episode_id,
        "checks": {
            "identity_consistency": identity,
            "sha256_integrity": sha_check,
            "stale_evidence": stale_check,
            "duration_compliance": duration_check,
            "possible_padding": padding_check,
        },
        "flags": [f for f in [stale_flag] if f] + (["POSSIBLE_PADDING"] if padding_check["status"] == "ADVISE" else []),
    }
