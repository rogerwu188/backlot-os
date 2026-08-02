from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .models import Project


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _clean(value: float) -> float:
    return round(float(value), 9)


def load_json_value(source: str | Path | dict[str, Any]) -> tuple[dict[str, Any], Path | None]:
    if isinstance(source, dict):
        return copy.deepcopy(source), None
    path = Path(source).resolve()
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must contain a JSON object")
    return value, path


def write_json_atomic(path: str | Path, value: dict[str, Any]) -> str:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return str(destination)


@dataclass(frozen=True)
class ClipRef:
    kind: str
    track_id: str
    track_index: int
    clip_index: int
    clip: dict[str, Any]

    @property
    def key(self) -> tuple[str, int, int]:
        return self.kind, self.track_index, self.clip_index

    @property
    def start(self) -> float:
        return float(self.clip.get("start", 0))

    @property
    def duration(self) -> float:
        return float(self.clip["duration"])

    def identity(self) -> dict[str, Any]:
        metadata = self.clip.get("metadata") or {}
        return {
            "trackKind": self.kind, "trackId": self.track_id, "trackIndex": self.track_index,
            "clipIndex": self.clip_index, "clipId": self.clip.get("id"), "metadata": copy.deepcopy(metadata),
        }


@dataclass(frozen=True)
class TransformResult:
    project: dict[str, Any]
    audit: dict[str, Any]
    diff: tuple[dict[str, Any], ...]
    total_trim: float

    def summary(self) -> dict[str, Any]:
        return {
            "beforeHash": self.audit["beforeHash"], "afterHash": self.audit["afterHash"],
            "planHash": self.audit["planHash"], "operationCount": len(self.audit["operations"]),
            "totalTrim": self.total_trim,
            "requireCutReason": self.audit.get("contract", {}).get("requireCutReason", False),
            "diff": list(self.diff),
        }


def _clips(project: dict[str, Any]) -> list[ClipRef]:
    result: list[ClipRef] = []
    timeline = project.get("timeline", {})
    for kind, key in (("video", "videoTracks"), ("audio", "audioTracks")):
        for track_index, track in enumerate(timeline.get(key, [])):
            if not track.get("enabled", True):
                continue
            track_id = str(track.get("id", f"{kind}{track_index}"))
            for clip_index, clip in enumerate(track.get("clips", [])):
                result.append(ClipRef(kind, track_id, track_index, clip_index, clip))
    return result


def _matches(ref: ClipRef, match: dict[str, Any]) -> bool:
    metadata = ref.clip.get("metadata") or {}
    checks = []
    if "clipId" in match:
        checks.append(ref.clip.get("id") == match["clipId"])
    if "dialogueId" in match:
        checks.append(metadata.get("dialogue_id") == match["dialogueId"])
    return bool(checks) and all(checks)


def _intersects(start: float, end: float, protected: dict[str, Any]) -> bool:
    return start < float(protected["end"]) and end > float(protected["start"])


def _number(value: Any, path: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{path} must be a number")
    result = float(value)
    if (positive and result <= 0) or (not positive and result < 0):
        raise ValidationError(f"{path} must be {'> 0' if positive else '>= 0'}")
    return result


def _validate_plan(plan: dict[str, Any], *, require_cut_reason: bool = False) -> bool:
    allowed_root = {"version", "expectedOperationCount", "expectedTotalTrim", "requireCutReason", "operations", "protections", "options"}
    unknown_root = set(plan) - allowed_root
    if unknown_root:
        raise ValidationError(f"unknown trim plan fields: {sorted(unknown_root)}")
    if plan.get("version", "1.0") != "1.0":
        raise ValidationError("trim plan version must be '1.0'")
    if "requireCutReason" in plan and not isinstance(plan["requireCutReason"], bool):
        raise ValidationError("requireCutReason must be a boolean")
    effective_require_cut_reason = require_cut_reason or bool(plan.get("requireCutReason", False))
    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValidationError("trim plan operations must be a non-empty array")
    seen_ids = set()
    for index, operation in enumerate(operations):
        path = f"operations[{index}]"
        if not isinstance(operation, dict):
            raise ValidationError(f"{path} must be an object")
        unknown_operation = set(operation) - {"id", "match", "headTrim", "contentGuard", "cutReason", "requiredTrackKinds"}
        if unknown_operation:
            raise ValidationError(f"{path} contains unknown fields: {sorted(unknown_operation)}")
        operation_id = operation.get("id", f"operation-{index}")
        if not isinstance(operation_id, str) or not operation_id:
            raise ValidationError(f"{path}.id must be a non-empty string")
        if operation_id in seen_ids:
            raise ValidationError(f"duplicate operation id: {operation_id}")
        seen_ids.add(operation_id)
        match = operation.get("match")
        if not isinstance(match, dict) or not ({"clipId", "dialogueId"} & match.keys()):
            raise ValidationError(f"{path}.match requires clipId and/or dialogueId")
        if set(match) - {"clipId", "dialogueId"}:
            raise ValidationError(f"{path}.match contains unknown fields")
        if any(not isinstance(value, str) or not value for value in match.values()):
            raise ValidationError(f"{path}.match values must be non-empty strings")
        _number(operation.get("headTrim"), f"{path}.headTrim", positive=True)
        if operation.get("contentGuard") != "silence-head":
            raise ValidationError(f"{path}.contentGuard must be 'silence-head'")
        cut_reason = operation.get("cutReason")
        if cut_reason is not None and (not isinstance(cut_reason, str) or not cut_reason.strip()):
            raise ValidationError(f"{path}.cutReason must be a non-empty string")
        if effective_require_cut_reason and not isinstance(cut_reason, str):
            raise ValidationError(f"{path}.cutReason is required by requireCutReason")
        kinds = operation.get("requiredTrackKinds", [])
        if not isinstance(kinds, list) or not set(kinds).issubset({"video", "audio"}):
            raise ValidationError(f"{path}.requiredTrackKinds must contain only video/audio")
    expected_count = plan.get("expectedOperationCount")
    if expected_count is not None and (isinstance(expected_count, bool) or not isinstance(expected_count, int) or expected_count <= 0):
        raise ValidationError("expectedOperationCount must be a positive integer")
    if "expectedTotalTrim" in plan:
        _number(plan["expectedTotalTrim"], "expectedTotalTrim")
    protections = plan.get("protections") or {}
    if not isinstance(protections, dict):
        raise ValidationError("protections must be an object")
    allowed_protections = {"beatIds", "clipIds", "dialogueIds", "frozenBeatIds", "frozenClipIds", "timeRanges"}
    if set(protections) - allowed_protections:
        raise ValidationError(f"protections contains unknown fields: {sorted(set(protections) - allowed_protections)}")
    for name in allowed_protections - {"timeRanges"}:
        values = protections.get(name, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
            raise ValidationError(f"protections.{name} must be an array of non-empty strings")
    ranges = protections.get("timeRanges", [])
    if not isinstance(ranges, list):
        raise ValidationError("protections.timeRanges must be an array")
    for index, interval in enumerate(ranges):
        if not isinstance(interval, dict) or "start" not in interval or "end" not in interval:
            raise ValidationError(f"protections.timeRanges[{index}] requires start/end")
        start = _number(interval["start"], f"protections.timeRanges[{index}].start")
        end = _number(interval["end"], f"protections.timeRanges[{index}].end", positive=True)
        if end <= start:
            raise ValidationError(f"protections.timeRanges[{index}].end must be greater than start")
    options = plan.get("options") or {}
    if not isinstance(options, dict):
        raise ValidationError("options must be an object")
    allowed_options = {"ripple", "requireSynchronizedStart", "requiredTrackKinds", "syncTolerance", "maxHeadTrim", "preserveTrackOrder"}
    if set(options) - allowed_options:
        raise ValidationError(f"options contains unknown fields: {sorted(set(options) - allowed_options)}")
    for name in ("ripple", "requireSynchronizedStart", "preserveTrackOrder"):
        if name in options and not isinstance(options[name], bool):
            raise ValidationError(f"options.{name} must be a boolean")
    kinds = options.get("requiredTrackKinds", [])
    if not isinstance(kinds, list) or not set(kinds).issubset({"video", "audio"}):
        raise ValidationError("options.requiredTrackKinds must contain only video/audio")
    return effective_require_cut_reason


def transform_project(project_value: dict[str, Any], plan_value: dict[str, Any], *, require_cut_reason: bool = False) -> TransformResult:
    before = copy.deepcopy(project_value)
    project = copy.deepcopy(project_value)
    plan = copy.deepcopy(plan_value)
    Project.parse(project)  # Structural and timeline validation before mutation.
    effective_require_cut_reason = _validate_plan(plan, require_cut_reason=require_cut_reason)
    protections = plan.get("protections") or {}
    if not isinstance(protections, dict):
        raise ValidationError("protections must be an object")
    protected_beats = set(protections.get("beatIds") or [])
    protected_clips = set(protections.get("clipIds") or [])
    protected_dialogues = set(protections.get("dialogueIds") or [])
    frozen_beats = set(protections.get("frozenBeatIds") or [])
    frozen_clips = set(protections.get("frozenClipIds") or [])
    time_ranges = protections.get("timeRanges") or []
    options = plan.get("options") or {}
    if not isinstance(options, dict):
        raise ValidationError("options must be an object")
    ripple = bool(options.get("ripple", True))
    require_sync = bool(options.get("requireSynchronizedStart", True))
    strict_order = bool(options.get("preserveTrackOrder", True))
    tolerance = _number(options.get("syncTolerance", 0.001), "options.syncTolerance")
    max_head_trim = options.get("maxHeadTrim")
    if max_head_trim is not None:
        max_head_trim = _number(max_head_trim, "options.maxHeadTrim", positive=True)

    original_fields = {
        ref.key: {"start": ref.start, "in": float(ref.clip.get("in", 0)), "duration": ref.duration,
                  "identity": ref.identity()} for ref in _clips(project)
    }
    touched: set[tuple[str, int, int]] = set()
    audit_operations: list[dict[str, Any]] = []
    total_trim = 0.0
    for operation_index, operation in enumerate(plan["operations"]):
        operation_id = operation.get("id", f"operation-{operation_index}")
        amount = _number(operation["headTrim"], f"operations[{operation_index}].headTrim", positive=True)
        if max_head_trim is not None and amount > max_head_trim + 1e-9:
            raise ValidationError(f"operation {operation_id} headTrim {amount:g}s exceeds maxHeadTrim {max_head_trim:g}s")
        refs = _clips(project)
        selected = [ref for ref in refs if _matches(ref, operation["match"])]
        if not selected:
            raise ValidationError(f"operation {operation_id} matched no clips")
        duplicate = [ref for ref in selected if ref.key in touched]
        if duplicate:
            raise ValidationError(f"operation {operation_id} targets a clip already trimmed by another operation")
        starts = [ref.start for ref in selected]
        if require_sync and max(starts) - min(starts) > tolerance:
            raise ValidationError(f"operation {operation_id} matched A/V clips with unsynchronized starts: {starts}")
        required_kinds = set(operation.get("requiredTrackKinds") or options.get("requiredTrackKinds") or [])
        actual_kinds = {ref.kind for ref in selected}
        if not required_kinds.issubset(actual_kinds):
            raise ValidationError(f"operation {operation_id} missing required track kinds: {sorted(required_kinds - actual_kinds)}")
        event_start = min(starts)
        if ripple and any(event_start < float(interval["end"]) - tolerance for interval in time_ranges):
            raise ValidationError(f"operation {operation_id} would ripple a protected time range")
        for ref in selected:
            metadata = ref.clip.get("metadata") or {}
            if (ref.clip.get("id") in protected_clips or ref.clip.get("id") in frozen_clips or
                    metadata.get("dialogue_id") in protected_dialogues or
                    metadata.get("beat_id") in protected_beats or metadata.get("beat_id") in frozen_beats):
                raise ValidationError(f"operation {operation_id} targets protected clip {ref.clip.get('id') or ref.clip_index}")
            if any(_intersects(ref.start, ref.start + ref.duration, interval) for interval in time_ranges):
                raise ValidationError(f"operation {operation_id} intersects a protected time range")
            if amount >= ref.duration - 1e-9:
                raise ValidationError(f"operation {operation_id} headTrim would remove all of clip {ref.clip.get('id') or ref.clip_index}")

        selected_keys = {ref.key for ref in selected}
        for ref in selected:
            ref.clip["in"] = _clean(float(ref.clip.get("in", 0)) + amount)
            ref.clip["duration"] = _clean(ref.duration - amount)
            touched.add(ref.key)
        ripple_affected = []
        if ripple:
            for ref in refs:
                if ref.key not in selected_keys and ref.start > event_start + tolerance:
                    metadata = ref.clip.get("metadata") or {}
                    if ref.clip.get("id") in frozen_clips or metadata.get("beat_id") in frozen_beats:
                        raise ValidationError(f"operation {operation_id} would ripple frozen clip {ref.clip.get('id') or ref.clip_index}")
                    new_start = ref.start - amount
                    if new_start < -tolerance:
                        raise ValidationError(f"operation {operation_id} would move a clip before time zero")
                    ref.clip["start"] = _clean(max(0.0, new_start))
                    ripple_affected.append(ref.identity())
        total_trim = _clean(total_trim + amount)
        audit_operations.append({
            "id": operation_id, "match": copy.deepcopy(operation["match"]), "headTrim": amount,
            "contentGuard": operation["contentGuard"], "cutReason": operation.get("cutReason"),
            "eventStart": event_start, "selectedClips": [ref.identity() for ref in selected],
            "rippleAffected": ripple_affected,
        })

    if strict_order:
        timeline = project.get("timeline", {})
        for kind, key in (("video", "videoTracks"), ("audio", "audioTracks")):
            for track_index, track in enumerate(timeline.get(key, [])):
                starts = [float(clip.get("start", 0)) for clip in track.get("clips", [])]
                if any(right + tolerance < left for left, right in zip(starts, starts[1:])):
                    raise ValidationError(f"transform would change locked order in {kind} track {track_index}")

    expected_count = plan.get("expectedOperationCount")
    if expected_count is not None and expected_count != len(audit_operations):
        raise ValidationError(f"expectedOperationCount {expected_count} does not match {len(audit_operations)}")
    expected_total = plan.get("expectedTotalTrim")
    if expected_total is not None and abs(_number(expected_total, "expectedTotalTrim") - total_trim) > 1e-6:
        raise ValidationError(f"expectedTotalTrim {expected_total} does not match {total_trim:g}")
    Project.parse(project)  # Prove the resulting project remains structurally valid.

    diff = []
    for ref in _clips(project):
        original = original_fields[ref.key]
        after = {"start": ref.start, "in": float(ref.clip.get("in", 0)), "duration": ref.duration}
        changes = {field: {"before": original[field], "after": after[field]}
                   for field in ("start", "in", "duration") if abs(original[field] - after[field]) > 1e-9}
        if changes:
            diff.append({**original["identity"], "changes": changes})
    diff.sort(key=lambda item: (item["trackKind"], item["trackIndex"], item["clipIndex"]))
    audit = {
        "version": "1.0", "action": "timeline-head-trim-ripple",
        "beforeHash": content_hash(before), "afterHash": content_hash(project), "planHash": content_hash(plan),
        "operationCount": len(audit_operations), "totalTrim": total_trim,
        "operations": audit_operations, "diff": diff,
        "contract": {"requireCutReason": effective_require_cut_reason},
        "invariants": {"speedChanged": False, "trackArrayOrderChanged": False},
        "rollbackProject": before,
    }
    return TransformResult(project, audit, tuple(diff), total_trim)


def rollback_project(audit_value: dict[str, Any]) -> dict[str, Any]:
    if audit_value.get("version") != "1.0" or "rollbackProject" not in audit_value:
        raise ValidationError("audit does not contain a supported rollbackProject")
    project = copy.deepcopy(audit_value["rollbackProject"])
    if content_hash(project) != audit_value.get("beforeHash"):
        raise ValidationError("rollback project hash does not match audit beforeHash")
    Project.parse(project)
    return project
