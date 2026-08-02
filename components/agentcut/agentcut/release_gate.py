from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_review(source: str | Path | dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    if isinstance(source, dict):
        return source, None
    path = Path(source).resolve()
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("full-cut visual review must be a JSON object")
    return value, str(path)


def validate_release_output(
    final_path: str | Path,
    review: str | Path | dict[str, Any],
    *,
    conditional_source_count: int = 0,
) -> dict[str, Any]:
    """Bind a full-cut visual review to the exact current final bytes.

    This is an evidence gate only. It never performs or authorizes a platform
    mutation, even when the final is clean.
    """
    final = Path(final_path).resolve()
    failures: list[str] = []
    try:
        final_sha = sha256_file(final)
    except OSError as exc:
        return {
            "status": "FAIL", "cleanRelease": False, "final": str(final),
            "finalSha256": None, "reviewPath": None,
            "failures": [f"RELEASE_FINAL_UNREADABLE:{type(exc).__name__}"],
            "conditionalSourceCount": conditional_source_count,
            "automaticPlatformReplacementAllowed": False,
            "platformMutationAuthorized": False,
        }
    try:
        value, review_path = _load_review(review)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "FAIL", "cleanRelease": False, "final": str(final),
            "finalSha256": final_sha, "reviewPath": str(review) if not isinstance(review, dict) else None,
            "failures": [f"RELEASE_REVIEW_UNREADABLE:{type(exc).__name__}"],
            "conditionalSourceCount": conditional_source_count,
            "automaticPlatformReplacementAllowed": False,
            "platformMutationAuthorized": False,
        }
    review_sha = value.get("media_sha256") or value.get("mediaSha256") or value.get("final_sha256") or value.get("finalSha256")
    scoring = value.get("scoring") if isinstance(value.get("scoring"), dict) else {}
    hard_gate = value.get("hard_gate_passed")
    if hard_gate is None:
        hard_gate = value.get("hardGatePassed")
    if hard_gate is None:
        hard_gate = scoring.get("hard_gate_passed", scoring.get("hardGatePassed"))
    scope = str(value.get("scope") or "").strip().lower().replace("-", "_")
    if value.get("schema") != "qingshan.review.report.v2":
        failures.append("RELEASE_REVIEW_SCHEMA_INVALID")
    if str(value.get("media_kind") or "").lower() != "video":
        failures.append("RELEASE_REVIEW_MEDIA_KIND_NOT_VIDEO")
    if scope not in {"final", "full_cut", "final_cut", "fullcut"}:
        failures.append("RELEASE_REVIEW_SCOPE_NOT_FULL_CUT")
    if not isinstance(review_sha, str) or len(review_sha) != 64:
        failures.append("RELEASE_REVIEW_FINAL_SHA_MISSING")
    elif review_sha.lower() != final_sha:
        failures.append("RELEASE_REVIEW_FINAL_SHA_MISMATCH")
    if hard_gate is not True:
        failures.append("RELEASE_VISUAL_HARD_GATE_NOT_PASSED")
    if conditional_source_count > 0:
        failures.append("RELEASE_CONDITIONAL_SOURCES_UNRESOLVED")
    clean = not failures
    return {
        "status": "PASS" if clean else "FAIL",
        "cleanRelease": clean,
        "final": str(final),
        "finalSha256": final_sha,
        "reviewPath": review_path,
        "reviewFinalSha256": review_sha,
        "shaMatches": isinstance(review_sha, str) and review_sha.lower() == final_sha,
        "reviewScope": scope or None,
        "reviewSchema": value.get("schema"),
        "reviewMediaKind": value.get("media_kind"),
        "hardGatePassed": hard_gate is True,
        "failures": failures,
        "conditionalSourceCount": conditional_source_count,
        "conditionalMachineAdmissionTriggersPlatformReplacement": False,
        "automaticPlatformReplacementAllowed": False,
        "platformMutationAuthorized": False,
        "nextAction": "explicit_release_authorization_required" if clean else "hold_release",
    }
