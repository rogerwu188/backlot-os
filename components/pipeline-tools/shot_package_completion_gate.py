#!/usr/bin/env python3
"""Fail-closed completion accounting for production shot packages.

The gate deliberately computes package state from evidence instead of trusting
an authored ``state`` field.  Prompt/reference precompilation is useful work,
but it never becomes an admitted clip or contributes video seconds until every
completion binding has passed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


SUPPORTED_SCHEMAS = frozenset(
    {
        "backlotos.shot_package_inventory.v1",
        "qingshan.shot_package_inventory.v1",
    }
)
PRODUCTION_VIDEO_MODEL = "seedance-2.0-fast"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
PASS_STATUSES = frozenset({"PASS", "ADMITTED"})
ADMITTED_QA_STATUSES = frozenset({"ADMITTED", "PASS_ADMITTED", "PASS_RELEASE_READY"})
NON_LIPSYNC_TRANSPORTS = frozenset({"VOICEOVER", "NARRATION", "OFFSCREEN"})
ASSET_CATEGORIES = ("characters", "wardrobe", "scenes", "props")


def _failure(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, **details}


def _is_sha256(value: Any) -> bool:
    return bool(SHA256_RE.fullmatch(str(value or "")))


def _same_sha(left: Any, right: Any) -> bool:
    return _is_sha256(left) and _is_sha256(right) and str(left).lower() == str(right).lower()


def _nonempty(value: Any) -> bool:
    return bool(str(value or "").strip())


def _require_sha(
    failures: list[dict[str, Any]],
    value: Any,
    code: str,
    **details: Any,
) -> None:
    if not _is_sha256(value):
        failures.append(_failure(code, **details))


def _binding_rows(
    package_id: str,
    bindings: Any,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    failures: list[dict[str, Any]] = []
    normalized: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(bindings, dict):
        return [_failure("ASSET_BINDINGS_MISSING", package_id=package_id)], normalized

    for category in ASSET_CATEGORIES:
        raw = bindings.get(category)
        if isinstance(raw, dict):
            applicable = raw.get("applicable")
            rows = raw.get("items")
            if not isinstance(applicable, bool):
                failures.append(
                    _failure(
                        "ASSET_BINDING_APPLICABILITY_MISSING",
                        package_id=package_id,
                        category=category,
                    )
                )
                applicable = True
            if applicable is False:
                if rows not in ([], None):
                    failures.append(
                        _failure(
                            "NON_APPLICABLE_ASSET_CATEGORY_MUST_BE_EMPTY",
                            package_id=package_id,
                            category=category,
                        )
                    )
                if not _nonempty(raw.get("reason")):
                    failures.append(
                        _failure(
                            "NON_APPLICABLE_ASSET_CATEGORY_REASON_MISSING",
                            package_id=package_id,
                            category=category,
                        )
                    )
                normalized[category] = []
                continue
        else:
            rows = raw
            applicable = True
        if not isinstance(rows, list) or (applicable is True and not rows):
            failures.append(
                _failure(
                    "ASSET_BINDING_CATEGORY_MISSING_OR_EMPTY",
                    package_id=package_id,
                    category=category,
                )
            )
            normalized[category] = []
            continue
        normalized[category] = rows
        seen_ids: set[str] = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                failures.append(
                    _failure(
                        "ASSET_BINDING_INVALID",
                        package_id=package_id,
                        category=category,
                        index=index,
                    )
                )
                continue
            asset_id = str(row.get("asset_id") or "").strip()
            if not asset_id:
                failures.append(
                    _failure(
                        "ASSET_ID_MISSING",
                        package_id=package_id,
                        category=category,
                        index=index,
                    )
                )
            elif asset_id in seen_ids:
                failures.append(
                    _failure(
                        "DUPLICATE_ASSET_ID_IN_CATEGORY",
                        package_id=package_id,
                        category=category,
                        asset_id=asset_id,
                    )
                )
            seen_ids.add(asset_id)
            _require_sha(
                failures,
                row.get("sha256"),
                "ASSET_SHA256_MISSING_OR_INVALID",
                package_id=package_id,
                category=category,
                asset_id=asset_id or None,
                index=index,
            )

    character_ids = {
        str(row.get("asset_id"))
        for row in normalized.get("characters", [])
        if isinstance(row, dict) and row.get("asset_id")
    }
    for row in normalized.get("wardrobe", []):
        if not isinstance(row, dict):
            continue
        character_id = str(row.get("character_id") or "").strip()
        if not character_id:
            failures.append(
                _failure(
                    "WARDROBE_CHARACTER_BINDING_MISSING",
                    package_id=package_id,
                    asset_id=row.get("asset_id"),
                )
            )
        elif character_id not in character_ids:
            failures.append(
                _failure(
                    "WARDROBE_CHARACTER_BINDING_UNKNOWN",
                    package_id=package_id,
                    asset_id=row.get("asset_id"),
                    character_id=character_id,
                )
            )
    return failures, normalized


def _precompile_failures(
    package: dict[str, Any],
    package_id: str,
    canonical_sha: Any,
    manifest_sha: Any,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    binding = package.get("canonical_binding")
    if not isinstance(binding, dict):
        failures.append(_failure("CANONICAL_BINDING_MISSING", package_id=package_id))
    else:
        if not _same_sha(binding.get("canonical_sha256"), canonical_sha):
            failures.append(_failure("PACKAGE_CANONICAL_SHA256_MISMATCH", package_id=package_id))
        if not _same_sha(binding.get("manifest_sha256"), manifest_sha):
            failures.append(_failure("PACKAGE_MANIFEST_SHA256_MISMATCH", package_id=package_id))

    prompt = package.get("prompt")
    if not isinstance(prompt, dict):
        failures.append(_failure("PROMPT_BINDING_MISSING", package_id=package_id))
    else:
        _require_sha(
            failures,
            prompt.get("sha256"),
            "PROMPT_SHA256_MISSING_OR_INVALID",
            package_id=package_id,
        )
        if str(prompt.get("status") or "").upper() != "PRECOMPILED":
            failures.append(_failure("PROMPT_NOT_PRECOMPILED", package_id=package_id))

    generation = package.get("generation")
    if not isinstance(generation, dict):
        failures.append(_failure("GENERATION_CONTRACT_MISSING", package_id=package_id))
    elif generation.get("model") != PRODUCTION_VIDEO_MODEL:
        failures.append(
            _failure(
                "NON_PRODUCTION_VIDEO_MODEL",
                package_id=package_id,
                expected=PRODUCTION_VIDEO_MODEL,
                actual=generation.get("model"),
            )
        )

    first_frame = package.get("first_frame")
    if not isinstance(first_frame, dict):
        failures.append(_failure("EXACT_FIRST_FRAME_BINDING_MISSING", package_id=package_id))
        first_frame_sha = None
    else:
        first_frame_sha = first_frame.get("sha256")
        _require_sha(
            failures,
            first_frame_sha,
            "FIRST_FRAME_SHA256_MISSING_OR_INVALID",
            package_id=package_id,
        )
        if first_frame.get("exact") is not True:
            failures.append(_failure("FIRST_FRAME_NOT_DECLARED_EXACT", package_id=package_id))

    references = package.get("ordered_references")
    if not isinstance(references, list) or not references:
        failures.append(_failure("ORDERED_REFERENCES_MISSING_OR_EMPTY", package_id=package_id))
    else:
        orders: list[int] = []
        first_frame_matches = 0
        for index, row in enumerate(references):
            if not isinstance(row, dict):
                failures.append(
                    _failure("ORDERED_REFERENCE_INVALID", package_id=package_id, index=index)
                )
                continue
            order = row.get("order")
            if not isinstance(order, int) or isinstance(order, bool):
                failures.append(
                    _failure("REFERENCE_ORDER_INVALID", package_id=package_id, index=index)
                )
            else:
                orders.append(order)
            _require_sha(
                failures,
                row.get("sha256"),
                "REFERENCE_SHA256_MISSING_OR_INVALID",
                package_id=package_id,
                index=index,
            )
            if str(row.get("role") or "").upper() == "FIRST_FRAME":
                if _same_sha(row.get("sha256"), first_frame_sha):
                    first_frame_matches += 1
                else:
                    failures.append(
                        _failure("ORDERED_FIRST_FRAME_SHA256_MISMATCH", package_id=package_id)
                    )
        if orders != list(range(1, len(references) + 1)):
            failures.append(
                _failure(
                    "REFERENCE_ORDER_NOT_CONTIGUOUS_FROM_ONE",
                    package_id=package_id,
                    actual=orders,
                )
            )
        if first_frame_matches != 1:
            failures.append(
                _failure(
                    "ORDERED_REFERENCES_REQUIRE_EXACTLY_ONE_BOUND_FIRST_FRAME",
                    package_id=package_id,
                    matches=first_frame_matches,
                )
            )

    binding_failures, _ = _binding_rows(package_id, package.get("asset_bindings"))
    failures.extend(binding_failures)
    return failures


def _dialogue_failures(package: dict[str, Any], package_id: str) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    dialogue = package.get("dialogue")
    if not isinstance(dialogue, dict) or not isinstance(dialogue.get("applicable"), bool):
        return [_failure("DIALOGUE_APPLICABILITY_MISSING", package_id=package_id)]
    if dialogue["applicable"] is False:
        return failures

    audio = dialogue.get("audio")
    if not isinstance(audio, dict):
        failures.append(_failure("DIALOGUE_AUDIO_BINDING_MISSING", package_id=package_id))
    else:
        _require_sha(
            failures,
            audio.get("sha256"),
            "DIALOGUE_AUDIO_SHA256_MISSING_OR_INVALID",
            package_id=package_id,
        )
        if str(audio.get("status") or "").upper() not in PASS_STATUSES:
            failures.append(_failure("DIALOGUE_AUDIO_NOT_PASS", package_id=package_id))

    lip_sync = dialogue.get("lip_sync")
    if not isinstance(lip_sync, dict) or not isinstance(lip_sync.get("applicable"), bool):
        failures.append(_failure("LIP_SYNC_APPLICABILITY_MISSING", package_id=package_id))
    elif lip_sync["applicable"] is True:
        if str(lip_sync.get("status") or "").upper() not in PASS_STATUSES:
            failures.append(_failure("LIP_SYNC_NOT_PASS", package_id=package_id))
        _require_sha(
            failures,
            lip_sync.get("qa_sha256"),
            "LIP_SYNC_QA_SHA256_MISSING_OR_INVALID",
            package_id=package_id,
        )
    else:
        transport = str(dialogue.get("transport") or "").upper()
        if transport not in NON_LIPSYNC_TRANSPORTS:
            failures.append(
                _failure(
                    "LIP_SYNC_WAIVER_TRANSPORT_INVALID",
                    package_id=package_id,
                    actual=dialogue.get("transport"),
                )
            )
        if not _nonempty(lip_sync.get("reason")):
            failures.append(_failure("LIP_SYNC_WAIVER_REASON_MISSING", package_id=package_id))
    return failures


def _completion_failures(
    package: dict[str, Any],
    package_id: str,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    generation = package.get("generation") if isinstance(package.get("generation"), dict) else {}
    if str(generation.get("status") or "").upper() != "COMPLETED":
        failures.append(_failure("VIDEO_GENERATION_NOT_COMPLETED", package_id=package_id))

    output = package.get("output")
    if not isinstance(output, dict):
        failures.append(_failure("OUTPUT_BINDING_MISSING", package_id=package_id))
        output_sha = None
        duration = None
    else:
        output_sha = output.get("sha256")
        _require_sha(
            failures,
            output_sha,
            "OUTPUT_SHA256_MISSING_OR_INVALID",
            package_id=package_id,
        )
        duration = output.get("duration_seconds")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            failures.append(_failure("OUTPUT_DURATION_MISSING_OR_INVALID", package_id=package_id))

    failures.extend(_dialogue_failures(package, package_id))

    qa = package.get("qa")
    if not isinstance(qa, dict):
        failures.append(_failure("QA_ADMISSION_BINDING_MISSING", package_id=package_id))
    else:
        if str(qa.get("status") or "").upper() not in ADMITTED_QA_STATUSES:
            failures.append(_failure("QA_NOT_ADMITTED", package_id=package_id))
        _require_sha(
            failures,
            qa.get("receipt_sha256"),
            "QA_RECEIPT_SHA256_MISSING_OR_INVALID",
            package_id=package_id,
        )
        if not _same_sha(qa.get("output_sha256"), output_sha):
            failures.append(_failure("QA_OUTPUT_SHA256_MISMATCH", package_id=package_id))
    return failures


def audit_shot_packages(payload: dict[str, Any]) -> dict[str, Any]:
    """Compute fail-closed package states and real admitted throughput."""
    global_failures: list[dict[str, Any]] = []
    if payload.get("schema") not in SUPPORTED_SCHEMAS:
        global_failures.append(
            _failure("UNSUPPORTED_SCHEMA", actual=payload.get("schema"))
        )

    canonical = payload.get("canonical")
    if not isinstance(canonical, dict):
        canonical = {}
        global_failures.append(_failure("CANONICAL_BINDING_MISSING"))
    canonical_sha = canonical.get("sha256")
    _require_sha(global_failures, canonical_sha, "CANONICAL_SHA256_MISSING_OR_INVALID")

    manifest = payload.get("manifest")
    if not isinstance(manifest, dict):
        manifest = {}
        global_failures.append(_failure("MANIFEST_BINDING_MISSING"))
    manifest_sha = manifest.get("sha256")
    _require_sha(global_failures, manifest_sha, "MANIFEST_SHA256_MISSING_OR_INVALID")
    if not _same_sha(manifest.get("canonical_sha256"), canonical_sha):
        global_failures.append(_failure("MANIFEST_CANONICAL_SHA256_MISMATCH"))

    packages = payload.get("packages")
    if not isinstance(packages, list) or not packages:
        global_failures.append(_failure("PACKAGES_MISSING_OR_EMPTY"))
        packages = []

    package_ids = [
        str(package.get("package_id") or "").strip()
        if isinstance(package, dict)
        else ""
        for package in packages
    ]
    for package_id in sorted({item for item in package_ids if package_ids.count(item) > 1 and item}):
        global_failures.append(_failure("DUPLICATE_PACKAGE_ID", package_id=package_id))

    reports: list[dict[str, Any]] = []
    admitted_seconds = 0.0
    completed_packages = 0
    precompile_only = 0
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            reports.append(
                {
                    "package_id": None,
                    "computed_state": "BLOCKED",
                    "failures": [_failure("PACKAGE_NOT_OBJECT", index=index)],
                }
            )
            continue
        package_id = package_ids[index]
        identity_failures: list[dict[str, Any]] = []
        if not package_id:
            package_id = f"@index:{index}"
            identity_failures.append(_failure("PACKAGE_ID_MISSING", index=index))
        precompile_failures = _precompile_failures(
            package,
            package_id,
            canonical_sha,
            manifest_sha,
        )
        precompile_failures = [*identity_failures, *precompile_failures]
        completion_failures = _completion_failures(package, package_id)
        if precompile_failures:
            computed_state = "BLOCKED"
        elif not completion_failures:
            computed_state = "COMPLETE"
            completed_packages += 1
            admitted_seconds += float(package["output"]["duration_seconds"])
        else:
            generation = package.get("generation") or {}
            if str(generation.get("status") or "").upper() in {"SUBMITTED", "RUNNING", "COMPLETED"}:
                computed_state = "IN_PROGRESS"
            else:
                computed_state = "PRECOMPILED"
                precompile_only += 1
        reports.append(
            {
                "package_id": package_id,
                "computed_state": computed_state,
                "precompile_gate": "PASS" if not precompile_failures else "FAIL",
                "completion_gate": "PASS" if not completion_failures else "FAIL",
                "failures": [*precompile_failures, *completion_failures],
            }
        )

    assembly_ready = bool(packages) and not global_failures and completed_packages == len(packages)
    return {
        "schema": "backlotos.shot_package_completion_gate.v1",
        "status": "PASS" if assembly_ready else "FAIL",
        "episode": payload.get("episode"),
        "throughput": {
            "completed_packages": completed_packages,
            "admitted_video_seconds": round(admitted_seconds, 3),
            "assembly_ready": assembly_ready,
            "precompile_only": precompile_only,
        },
        "total_packages": len(packages),
        "packages": reports,
        "failures": global_failures,
        "policy": {
            "complete_is_computed_not_declared": True,
            "required_video_model": PRODUCTION_VIDEO_MODEL,
            "precompiled_is_not_complete": True,
            "precompiled_counts_as_admitted_clip": False,
            "precompiled_counts_as_admitted_video_seconds": False,
            "assembly_ready_requires_every_package_complete": True,
        },
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Durably replace one JSON output without exposing a partial document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _read_cli_json(value: str) -> dict[str, Any]:
    if value == "-":
        payload = json.load(sys.stdin)
    else:
        payload = json.loads(Path(value).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON value must be an object")
    return payload


def _invalid_input_report(exc: Exception) -> dict[str, Any]:
    return {
        "schema": "backlotos.shot_package_completion_gate.v1",
        "status": "FAIL",
        "throughput": {
            "completed_packages": 0,
            "admitted_video_seconds": 0.0,
            "assembly_ready": False,
            "precompile_only": 0,
        },
        "total_packages": 0,
        "packages": [],
        "failures": [
            _failure(
                "INPUT_JSON_INVALID",
                error_type=type(exc).__name__,
                message=str(exc),
            )
        ],
        "policy": {"fail_closed_on_invalid_input": True},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute admitted shot-package throughput from exact JSON bindings."
    )
    parser.add_argument("--input", "--in", dest="input_path", required=True)
    parser.add_argument("--output", "--out", dest="output_path")
    args = parser.parse_args(argv)
    try:
        report = audit_shot_packages(_read_cli_json(args.input_path))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = _invalid_input_report(exc)

    if args.output_path and args.output_path != "-":
        write_json_atomic(Path(args.output_path), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
