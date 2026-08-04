from __future__ import annotations

import json
import hashlib
import math
import os
import shutil
import struct
import subprocess
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import AgentCutError
from .models import Project
from .release_gate import validate_release_output
from .shot_recipes import validate_and_materialize_shot_recipes


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    track_id: str | None = None
    track_kind: str | None = None
    track_index: int | None = None
    clip_index: int | None = None
    clip_id: str | None = None
    metadata: dict[str, Any] | None = None
    time_range: dict[str, float] | None = None
    source_range: dict[str, float] | None = None
    source: str | None = None
    related_clips: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        names = {
            "track_id": "trackId", "track_kind": "trackKind", "track_index": "trackIndex", "clip_index": "clipIndex",
            "clip_id": "clipId", "time_range": "timeRange", "source_range": "sourceRange",
            "related_clips": "relatedClips",
        }
        return {names.get(k, k): v for k, v in raw.items() if v is not None}


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    duration: float
    video_tracks: int
    audio_tracks: int
    subtitle_tracks: int
    issues: tuple[ValidationIssue, ...]
    media: dict[str, dict[str, Any]]
    coverage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid, "duration": self.duration,
            "videoTracks": self.video_tracks, "audioTracks": self.audio_tracks,
            "subtitleTracks": self.subtitle_tracks,
            "issues": [x.to_dict() for x in self.issues],
            "media": self.media, "coverage": self.coverage,
        }


def _range(start: float, end: float) -> dict[str, float]:
    return {"start": start, "end": end, "duration": end - start}


def _merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + 1e-6:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(x[0], x[1]) for x in merged]


def _gaps(intervals: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    merged = _merge([(max(0, a), min(duration, b)) for a, b in intervals if b > 0 and a < duration])
    gaps: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in merged:
        if start > cursor + 1e-6:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration - 1e-6:
        gaps.append((cursor, duration))
    return gaps


def _font_codepoints(path: str) -> set[int]:
    """Read Unicode cmap format 4/12 from TTF, OTF or the first face of a TTC."""
    with open(path, "rb") as stream:
        data = stream.read()
    face = 0
    if data[:4] == b"ttcf":
        if len(data) < 16:
            raise ValueError("invalid TTC header")
        face = struct.unpack_from(">I", data, 12)[0]
    if face + 12 > len(data):
        raise ValueError("invalid font offset table")
    tables = struct.unpack_from(">H", data, face + 4)[0]
    cmap_offset = None
    for i in range(tables):
        offset = face + 12 + i * 16
        tag, _checksum, table_offset, _length = struct.unpack_from(">4sIII", data, offset)
        if tag == b"cmap":
            cmap_offset = table_offset
            break
    if cmap_offset is None:
        raise ValueError("font has no cmap table")
    count = struct.unpack_from(">H", data, cmap_offset + 2)[0]
    subtable_offsets = []
    for i in range(count):
        platform, encoding, relative = struct.unpack_from(">HHI", data, cmap_offset + 4 + i * 8)
        if platform == 0 or (platform == 3 and encoding in {1, 10}):
            subtable_offsets.append(cmap_offset + relative)
    codepoints: set[int] = set()
    for offset in set(subtable_offsets):
        fmt = struct.unpack_from(">H", data, offset)[0]
        if fmt == 12:
            groups = struct.unpack_from(">I", data, offset + 12)[0]
            for i in range(groups):
                start, end, _glyph = struct.unpack_from(">III", data, offset + 16 + i * 12)
                codepoints.update(range(start, end + 1))
        elif fmt == 4:
            seg_count = struct.unpack_from(">H", data, offset + 6)[0] // 2
            end_codes = struct.unpack_from(f">{seg_count}H", data, offset + 14)
            start_at = offset + 16 + seg_count * 2
            start_codes = struct.unpack_from(f">{seg_count}H", data, start_at)
            for start, end in zip(start_codes, end_codes):
                if start <= end and start != 0xFFFF:
                    codepoints.update(range(start, end + 1))
    return codepoints


def validate_subtitles(project: Project) -> tuple[list[ValidationIssue], dict[str, Any]]:
    issues: list[ValidationIssue] = []
    enabled = [(i, t) for i, t in enumerate(project.subtitle_tracks) if t.enabled]
    captions = [(ti, track, ci, clip) for ti, track in enabled for ci, clip in enumerate(track.clips)]
    if project.require_burned_subtitles and not captions:
        issues.append(ValidationIssue("SUBTITLE_TRACK_REQUIRED", "error", "requireBurnedSubtitles=true but no enabled caption clips exist", track_kind="subtitle"))
    by_dialogue: dict[str, list[dict[str, Any]]] = {}
    font_cache: dict[str, set[int] | Exception] = {}
    for track_index, track, clip_index, clip in captions:
        common = dict(
            track_id=track.id, track_kind="subtitle", track_index=track_index, clip_index=clip_index,
            clip_id=clip.id, metadata=clip.metadata or None,
            time_range=_range(clip.start, clip.start + clip.duration),
        )
        if not clip.text.strip():
            issues.append(ValidationIssue("SUBTITLE_EMPTY_TEXT", "error", "caption text cannot be empty", **common))
        if clip.start + clip.duration > project.main_duration + 1e-3:
            issues.append(ValidationIssue("SUBTITLE_OUT_OF_BOUNDS", "error", f"caption ends at {clip.start + clip.duration:g}s after main timeline duration {project.main_duration:g}s", **common))
        if not clip.dialogue_id:
            issues.append(ValidationIssue("SUBTITLE_DIALOGUE_ID_REQUIRED", "error", "caption requires dialogue_id", **common))
        else:
            by_dialogue.setdefault(clip.dialogue_id, []).append({"trackId": track.id, "clipIndex": clip_index, "clipId": clip.id})
        font = clip.style.font
        if not Path(font).is_file():
            issues.append(ValidationIssue("SUBTITLE_FONT_MISSING", "error", f"font must be an existing font file: {font}", **common))
        elif clip.text.strip():
            if font not in font_cache:
                try:
                    font_cache[font] = _font_codepoints(font)
                except Exception as exc:
                    font_cache[font] = exc
            supported = font_cache[font]
            if isinstance(supported, Exception):
                issues.append(ValidationIssue("SUBTITLE_FONT_INVALID", "error", f"cannot inspect font glyphs: {supported}", **common))
            else:
                missing = sorted({ch for ch in clip.text if not ch.isspace() and ord(ch) not in supported})
                if missing:
                    preview = "".join(missing[:20])
                    issues.append(ValidationIssue("SUBTITLE_GLYPH_MISSING", "error", f"font lacks glyphs for: {preview}", **common))
    ordered = sorted(captions, key=lambda item: item[3].start)
    for left_pos, (left_ti, left_track, left_i, left) in enumerate(ordered):
        left_end = left.start + left.duration
        for right_ti, right_track, right_i, right in ordered[left_pos + 1:]:
            if right.start >= left_end - 1e-6:
                break
            issues.append(ValidationIssue(
                "SUBTITLE_OVERLAP", "error", "caption clips overlap",
                track_id=right_track.id, track_kind="subtitle", track_index=right_ti,
                clip_index=right_i, clip_id=right.id,
                time_range=_range(right.start, min(left_end, right.start + right.duration)),
                related_clips=[{"trackId": left_track.id, "clipIndex": left_i, "clipId": left.id, "dialogueId": left.dialogue_id}],
            ))
    duplicates = sorted(k for k, values in by_dialogue.items() if len(values) != 1)
    for dialogue_id in duplicates:
        issues.append(ValidationIssue("SUBTITLE_DIALOGUE_ID_DUPLICATE", "error", f"dialogue_id appears in multiple captions: {dialogue_id}", track_kind="subtitle", related_clips=by_dialogue[dialogue_id]))
    expected = list(project.expected_dialogue_ids)
    actual = list(by_dialogue)
    missing = [x for x in expected if x not in by_dialogue]
    unexpected = [x for x in actual if x not in set(expected)] if expected else []
    duplicate_expected = sorted(x for x in set(expected) if expected.count(x) > 1)
    if duplicate_expected:
        issues.append(ValidationIssue("EXPECTED_DIALOGUE_ID_DUPLICATE", "error", f"expectedDialogueIds contains duplicates: {', '.join(duplicate_expected)}", track_kind="subtitle"))
    if project.require_burned_subtitles and expected and (missing or unexpected or duplicates):
        issues.append(ValidationIssue("SUBTITLE_COVERAGE_MISMATCH", "error", f"subtitle dialogue coverage is {len(expected)-len(missing)}/{len(expected)}", track_kind="subtitle"))
    matched = [x for x in expected if x in by_dialogue and len(by_dialogue[x]) == 1]
    coverage = {
        "required": project.require_burned_subtitles,
        "expectedCount": len(expected), "captionCount": len(captions), "matchedCount": len(matched),
        "count": f"{len(matched)}/{len(expected)}" if expected else f"{len(captions)}/{len(captions)}",
        "expectedDialogueIds": expected, "captionDialogueIds": actual,
        "matchedDialogueIds": matched, "missingDialogueIds": missing,
        "unexpectedDialogueIds": unexpected, "duplicateDialogueIds": duplicates,
    }
    return issues, coverage


def validate_release_project_contract(project: Project) -> tuple[list[ValidationIssue], dict[str, Any]]:
    """Require complete subtitle, outro, and visual-review declarations for releases."""
    required = bool(project.release_project)
    if not required:
        return [], {
            "required": False,
            "burnedSubtitlesRequired": project.require_burned_subtitles,
            "expectedDialogueCount": len(project.expected_dialogue_ids),
            "brandedOutroRequired": project.require_branded_outro,
            "outroEnabled": project.outro.enabled,
            "fullCutVisualReviewRequired": bool(project.release_gate.get("required", False)),
        }

    issues: list[ValidationIssue] = []
    checks = {
        "burnedSubtitlesRequired": project.require_burned_subtitles,
        "expectedDialogueCount": len(project.expected_dialogue_ids),
        "brandedOutroRequired": project.require_branded_outro,
        "outroEnabled": project.outro.enabled,
        "fullCutVisualReviewRequired": bool(project.release_gate.get("required", False)),
    }
    if not project.require_burned_subtitles:
        issues.append(ValidationIssue(
            "RELEASE_SUBTITLES_REQUIRED", "error",
            "release projects must set requireBurnedSubtitles=true",
            track_kind="subtitle",
        ))
    if not project.expected_dialogue_ids:
        issues.append(ValidationIssue(
            "RELEASE_DIALOGUE_IDS_REQUIRED", "error",
            "release projects must declare non-empty expectedDialogueIds",
            track_kind="subtitle",
        ))
    if not project.require_branded_outro:
        issues.append(ValidationIssue(
            "RELEASE_OUTRO_REQUIRED", "error",
            "release projects must set requireBrandedOutro=true",
            track_kind="outro",
        ))
    if not project.outro.enabled:
        issues.append(ValidationIssue(
            "RELEASE_OUTRO_ENABLED_REQUIRED", "error",
            "release projects must enable the branded outro",
            track_kind="outro",
        ))
    if not project.release_gate.get("required", False):
        issues.append(ValidationIssue(
            "RELEASE_VISUAL_GATE_REQUIRED", "error",
            "release projects must set releaseGate.required=true",
        ))
    return issues, {
        "required": True,
        **checks,
        "status": "PASS" if not issues else "FAIL",
    }


def validate_replacement_bindings(project: Project) -> tuple[list[ValidationIssue], dict[str, Any]]:
    """Prove that repaired clips are bound to the exact admitted replacement files."""
    raw_policy = project.metadata.get("replacementBindingPolicy")
    replacement_markers = []
    for track in project.video_tracks:
        if not track.enabled:
            continue
        for clip in track.clips:
            metadata = clip.metadata
            marked = any(
                key in metadata for key in (
                    "original_source", "v18_original_source", "superseded_source",
                    "replacement_generation_id", "shot_recipe_superseded",
                )
            ) or "SATISFIED" in str(metadata.get("replacement_condition") or "").upper()
            if marked:
                replacement_markers.append(clip.id)
    if raw_policy is None and project.release_project and replacement_markers:
        issue = ValidationIssue(
            "REPLACEMENT_BINDING_POLICY_REQUIRED", "error",
            "release project contains repaired clips but no enabled replacementBindingPolicy",
            related_clips=[{"clipId": clip_id} for clip_id in replacement_markers if clip_id],
        )
        return [issue], {"required": True, "status": "FAIL", "expected": len(replacement_markers),
                         "matched": 0, "residualClips": [{"clipId": value, "reason": issue.code} for value in replacement_markers]}
    if raw_policy is not None and not isinstance(raw_policy, dict):
        issue = ValidationIssue("REPLACEMENT_BINDING_POLICY_INVALID", "error", "replacementBindingPolicy must be an object")
        return [issue], {"required": True, "status": "FAIL", "expected": 0, "matched": 0,
                         "residualClips": [{"clipId": None, "reason": issue.code}]}
    policy = raw_policy or {}
    if not policy.get("enabled", False):
        return [], {"required": False, "status": "NOT_CONFIGURED", "expected": 0, "matched": 0, "residualClips": []}

    issues: list[ValidationIssue] = []
    targets = policy.get("targets", [])
    raw_forbidden_shas = policy.get("forbiddenSourceSha256", [])
    raw_forbidden_tokens = policy.get("forbiddenPathTokens", [])
    forbidden_shas = {str(value).lower() for value in raw_forbidden_shas if value} if isinstance(raw_forbidden_shas, list) else set()
    forbidden_tokens = [str(value).lower() for value in raw_forbidden_tokens if value] if isinstance(raw_forbidden_tokens, list) else []
    expected_count = policy.get("expectedTargetCount", len(targets))
    clips_by_id: dict[str, list[tuple[int, int, Any]]] = {}
    enabled_clips: list[tuple[int, int, Any]] = []
    for track_index, track in enumerate(project.video_tracks):
        if not track.enabled:
            continue
        for clip_index, clip in enumerate(track.clips):
            if clip.opacity <= 0:
                continue
            enabled_clips.append((track_index, clip_index, clip))
            if clip.id:
                clips_by_id.setdefault(clip.id, []).append((track_index, clip_index, clip))

    residual: list[dict[str, Any]] = []
    matched = 0
    sha_cache: dict[str, str] = {}

    def source_sha(path: str) -> str:
        if path in sha_cache:
            return sha_cache[path]
        source = Path(path)
        actual = ""
        if source.is_file():
            digest = hashlib.sha256()
            with source.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            actual = digest.hexdigest()
        sha_cache[path] = actual
        return actual

    if not isinstance(targets, list):
        targets = []
        issues.append(ValidationIssue("REPLACEMENT_BINDING_TARGETS_INVALID", "error", "replacementBindingPolicy.targets must be an array"))
    if not isinstance(raw_forbidden_shas, list) or not isinstance(raw_forbidden_tokens, list):
        issues.append(ValidationIssue(
            "REPLACEMENT_BINDING_FORBIDDEN_LIST_INVALID", "error",
            "forbiddenSourceSha256 and forbiddenPathTokens must be arrays",
        ))
    if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 1 or expected_count != len(targets):
        issues.append(ValidationIssue(
            "REPLACEMENT_BINDING_COVERAGE_INCOMPLETE", "error",
            f"replacement binding target count is {len(targets)} but expectedTargetCount is {expected_count!r}",
        ))
    target_ids = [target.get("clipId") for target in targets if isinstance(target, dict)]
    duplicate_target_ids = sorted({str(value) for value in target_ids if value and target_ids.count(value) > 1})
    if duplicate_target_ids:
        issues.append(ValidationIssue(
            "REPLACEMENT_BINDING_TARGET_DUPLICATE", "error",
            "replacement binding policy declares duplicate targets: " + ", ".join(duplicate_target_ids),
        ))

    for target in targets:
        if not isinstance(target, dict):
            issues.append(ValidationIssue("REPLACEMENT_BINDING_TARGET_INVALID", "error", "replacement binding target must be an object"))
            continue
        clip_id = target.get("clipId")
        expected_sha = str(target.get("replacementSourceSha256") or "").lower()
        found = clips_by_id.get(str(clip_id), [])
        if len(found) != 1:
            code = "REPLACEMENT_BINDING_TARGET_MISSING" if not found else "REPLACEMENT_BINDING_TARGET_DUPLICATE"
            issues.append(ValidationIssue(code, "error", f"replacement target {clip_id!r} occurs {len(found)} times", clip_id=str(clip_id) if clip_id else None))
            residual.append({"clipId": clip_id, "reason": code, "occurrences": len(found)})
            continue
        track_index, clip_index, clip = found[0]
        common = dict(track_id=project.video_tracks[track_index].id, track_kind="video", track_index=track_index,
                      clip_index=clip_index, clip_id=clip.id, source=clip.source,
                      time_range=_range(clip.start, clip.start + clip.duration))
        actual_sha = source_sha(clip.source)
        if not expected_sha or actual_sha != expected_sha:
            issues.append(ValidationIssue(
                "REPLACEMENT_BINDING_SHA_MISMATCH", "error",
                f"clip must bind replacement SHA {expected_sha or '<missing>'}, actual {actual_sha or '<unreadable>'}", **common,
            ))
            residual.append({"clipId": clip.id, "reason": "REPLACEMENT_BINDING_SHA_MISMATCH", "source": clip.source,
                             "expectedSha256": expected_sha, "actualSha256": actual_sha})
            continue
        metadata_sha = str(clip.metadata.get("source_sha256") or "").lower()
        if metadata_sha != actual_sha:
            issues.append(ValidationIssue(
                "REPLACEMENT_BINDING_METADATA_SHA_MISMATCH", "error",
                f"clip metadata source_sha256 {metadata_sha or '<missing>'} does not match bound file {actual_sha}", **common,
            ))
            residual.append({"clipId": clip.id, "reason": "REPLACEMENT_BINDING_METADATA_SHA_MISMATCH", "source": clip.source})
            continue
        matched += 1

    for track_index, clip_index, clip in enabled_clips:
        source_lower = clip.source.lower()
        metadata_sha = str(clip.metadata.get("source_sha256") or "").lower()
        actual_sha = source_sha(clip.source)
        reasons = []
        if actual_sha in forbidden_shas or metadata_sha in forbidden_shas:
            reasons.append("forbidden_source_sha")
        matched_tokens = [token for token in forbidden_tokens if token in source_lower]
        if matched_tokens:
            reasons.append("forbidden_path_token:" + ",".join(matched_tokens))
        if reasons:
            issues.append(ValidationIssue(
                "SUPERSEDED_SOURCE_STILL_BOUND", "error",
                "superseded source remains bound: " + "; ".join(reasons),
                track_id=project.video_tracks[track_index].id, track_kind="video", track_index=track_index,
                clip_index=clip_index, clip_id=clip.id, source=clip.source,
                time_range=_range(clip.start, clip.start + clip.duration),
            ))
            residual.append({"clipId": clip.id, "reason": "SUPERSEDED_SOURCE_STILL_BOUND", "source": clip.source})

    return issues, {
        "required": True, "status": "PASS" if not issues else "FAIL",
        "expected": expected_count, "declared": len(targets), "matched": matched,
        "residualClips": residual,
    }


def validate_outro(project: Project, ffmpeg: str | None = None) -> tuple[list[ValidationIssue], dict[str, Any]]:
    outro = project.outro
    if not outro.enabled:
        issues = []
        if project.require_branded_outro:
            issues.append(ValidationIssue("BRANDED_OUTRO_REQUIRED", "error", "requireBrandedOutro=true but no outro is enabled", track_kind="outro"))
        return issues, {"present": False, "enabled": False, "brand": None, "duration": 0,
                        "endsAtTimelineEnd": False, "required": project.require_branded_outro}
    issues: list[ValidationIssue] = []
    asset = Path(outro.asset_path)
    configured_start = project.main_duration if outro.start is None else outro.start
    configured_end = configured_start + outro.duration
    common = dict(track_id="NaluMotion.Outro", track_kind="outro", source=str(asset),
                  time_range=_range(configured_start, configured_end))
    if project.require_branded_outro and outro.brand != "nalu_motion":
        issues.append(ValidationIssue("OUTRO_BRAND_INVALID", "error", "required branded outro must use brand=nalu_motion", **common))
    if abs(configured_start - project.main_duration) > 1e-3:
        issues.append(ValidationIssue("OUTRO_NOT_AT_TIMELINE_END", "error", f"outro.start must equal main timeline end {project.main_duration:g}s", **common))
    if project.require_branded_outro and outro.fit == "cover":
        issues.append(ValidationIssue("OUTRO_BRAND_CROP_RISK", "error", "required Nalu Motion outro cannot use fit=cover because brand pixels may be cropped", **common))
    if not outro.template.strip() or not outro.template_version.strip():
        issues.append(ValidationIssue("OUTRO_TEMPLATE_EMPTY", "error", "enabled outro requires template and templateVersion", **common))
    if not asset.is_absolute():
        issues.append(ValidationIssue("OUTRO_ASSET_NOT_ABSOLUTE", "error", "outro.assetPath must be absolute", **common))
    if not asset.is_file():
        issues.append(ValidationIssue("OUTRO_ASSET_MISSING", "error", "enabled outro asset is missing; silent skip is forbidden", **common))
    elif asset.stat().st_size == 0:
        issues.append(ValidationIssue("OUTRO_ASSET_EMPTY", "error", "enabled outro asset is empty", **common))
    else:
        probe_binary = str(Path(ffmpeg).with_name("ffprobe")) if ffmpeg else "ffprobe"
        if not Path(probe_binary).is_file():
            probe_binary = shutil.which("ffprobe") or probe_binary
        probe = subprocess.run([probe_binary, "-v", "error", "-show_entries", "stream=codec_type,duration,width,height:format=duration", "-of", "json", str(asset)], capture_output=True, text=True)
        try:
            media = json.loads(probe.stdout) if probe.returncode == 0 else {}
            streams = media.get("streams", [])
        except json.JSONDecodeError:
            streams = []
        if not any(item.get("codec_type") == "video" for item in streams):
            issues.append(ValidationIssue("OUTRO_ASSET_UNREADABLE", "error", "outro asset has no readable video/image stream", **common))
        if asset.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            values = [item.get("duration") for item in streams if item.get("codec_type") == "video"] + [media.get("format", {}).get("duration")]
            durations = []
            for value in values:
                try:
                    durations.append(float(value))
                except (TypeError, ValueError):
                    pass
            if not durations or max(durations) + 1e-3 < outro.duration:
                issues.append(ValidationIssue("OUTRO_ASSET_DURATION_SHORT", "error", "outro video asset is shorter than configured duration", **common))
    if not outro.brand_text.strip() and not asset.is_file():
        issues.append(ValidationIssue("OUTRO_BRAND_EMPTY", "error", "outro requires brandText or a valid brand asset", **common))
    if abs(project.output.width / project.output.height - 9 / 16) > 0.005:
        issues.append(ValidationIssue("OUTRO_NOT_9X16", "error", "Nalu Motion outro requires a 9:16 output", **common))
    if outro.transition_in + outro.transition_out > outro.duration + 1e-6:
        issues.append(ValidationIssue("OUTRO_TRANSITION_OUT_OF_BOUNDS", "error", "outro transitions exceed its duration", **common))
    safe, logo = outro.safe_area, outro.logo
    if (logo["x"] < safe["left"] or logo["y"] < safe["top"] or
            logo["x"] + logo["width"] > project.output.width - safe["right"] or
            logo["y"] + logo["height"] > project.output.height - safe["bottom"]):
        issues.append(ValidationIssue("OUTRO_SAFE_AREA_OVERFLOW", "error", "outro logo exceeds the 9:16 safe area", **common))
    # Captions and dialogue must end no later than the append boundary. This is
    # deliberately checked independently from subtitle coverage.
    captions = [c for t in project.subtitle_tracks if t.enabled for c in t.clips]
    dialogue = [c for t in project.audio_tracks if t.enabled and ("dialogue" in t.id.lower() or "voice" in t.id.lower()) for c in t.clips]
    for kind, clips in (("subtitle", captions), ("dialogue", dialogue)):
        latest = max((c.start + c.duration for c in clips), default=0)
        if latest > project.main_duration + 1e-3:
            issues.append(ValidationIssue("OUTRO_LAST_DIALOGUE_OVERLAP", "error", f"{kind} extends into outro append boundary", **common))
    audio_assets = [("audioPath", outro.audio_path), ("sfxPath", outro.sfx_path)]
    if outro.audio_policy == "asset" and not outro.audio_path:
        issues.append(ValidationIssue("OUTRO_AUDIO_POLICY_UNSATISFIED", "error", "audioPolicy=asset requires audioPath", **common))
    if outro.audio_policy == "mix" and not (outro.audio_path or outro.sfx_path):
        issues.append(ValidationIssue("OUTRO_AUDIO_POLICY_UNSATISFIED", "error", "audioPolicy=mix requires audioPath or sfxPath", **common))
    if outro.audio_policy == "silence" and (outro.audio_path or outro.sfx_path):
        issues.append(ValidationIssue("OUTRO_AUDIO_POLICY_UNSATISFIED", "error", "audioPolicy=silence forbids audioPath and sfxPath", **common))
    audio_manifest = []
    for field_name, value in audio_assets:
        if not value:
            continue
        path = Path(value)
        if not path.is_absolute() or not path.is_file() or path.stat().st_size == 0:
            issues.append(ValidationIssue("OUTRO_AUDIO_MISSING", "error", f"outro.{field_name} must be an existing non-empty absolute file", source=str(path), **{k: v for k, v in common.items() if k != "source"}))
            continue
        peak = None
        if ffmpeg:
            probe = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
            match = re.search(r"max_volume:\s*(-?inf|[-+0-9.]+) dB", probe.stderr)
            if probe.returncode or not match:
                issues.append(ValidationIssue("OUTRO_AUDIO_UNREADABLE", "error", f"cannot measure outro.{field_name}", source=str(path), **{k: v for k, v in common.items() if k != "source"}))
            else:
                peak = -120.0 if match.group(1) == "-inf" else float(match.group(1))
                if peak >= -0.1:
                    issues.append(ValidationIssue("OUTRO_AUDIO_DIGITAL_ZERO", "error", f"outro.{field_name} peaks at {peak:g} dBFS", source=str(path), **{k: v for k, v in common.items() if k != "source"}))
        audio_manifest.append({"kind": field_name, "path": str(path), "peakDbfs": peak})
    ends_at_end = abs(configured_end - project.duration) <= 1e-3 and abs(configured_start - project.main_duration) <= 1e-3
    return issues, {"present": True, "enabled": True, "required": project.require_branded_outro,
                    "brand": outro.brand, "template": outro.template,
                    "templateVersion": outro.template_version, "actualStart": project.main_duration,
                    "configuredStart": configured_start, "actualEnd": project.duration, "duration": outro.duration,
                    "endsAtTimelineEnd": ends_at_end, "fit": outro.fit, "audioPolicy": outro.audio_policy,
                    "assetPath": outro.asset_path,
                    "includeInTotalDuration": outro.include_in_total_duration,
                    "accountedDuration": project.duration if outro.include_in_total_duration else project.main_duration,
                    "dialogueDuckDb": outro.dialogue_duck_db, "bgmDuckDb": outro.bgm_duck_db, "audio": audio_manifest}


def validate_cleanup_regions(project: Project) -> tuple[list[ValidationIssue], dict[str, Any]]:
    issues: list[ValidationIssue] = []
    operations: list[dict[str, Any]] = []
    bottom_styles = [clip.style for track in project.subtitle_tracks if track.enabled for clip in track.clips
                     if clip.style.alignment.startswith("bottom")]
    safe_band_start = min((project.output.height - style.margins["bottom"] - max(100, style.size * 2 + style.outline * 2)
                           for style in bottom_styles), default=project.output.height)
    for track_index, track in enumerate(project.video_tracks):
        if not track.enabled:
            continue
        for clip_index, clip in enumerate(track.clips):
            for cleanup_index, cleanup in enumerate(clip.cleanup_regions):
                end = cleanup.start + (cleanup.duration or clip.duration - cleanup.start)
                common = dict(track_id=track.id, track_kind="video", track_index=track_index, clip_index=clip_index,
                              clip_id=clip.id, metadata=clip.metadata or None, source=clip.source,
                              time_range=_range(clip.start + cleanup.start, clip.start + end))
                if cleanup.x + cleanup.width > project.output.width or cleanup.y + cleanup.height > project.output.height:
                    issues.append(ValidationIssue("CLEANUP_REGION_OUT_OF_BOUNDS", "error", "cleanup region exceeds output frame bounds", **common))
                if cleanup.start < 0 or end > clip.duration + 1e-6 or end <= cleanup.start:
                    issues.append(ValidationIssue("CLEANUP_TIME_OUT_OF_BOUNDS", "error", "cleanup time exceeds its video clip", **common))
                overlaps_safe_band = cleanup.y + cleanup.height > safe_band_start
                if overlaps_safe_band and not cleanup.allow_caption_safe_band:
                    issues.append(ValidationIssue("CLEANUP_CAPTION_SAFE_BAND_OVERLAP", "error", f"cleanup intersects caption safe band y={safe_band_start:g}..{project.output.height}; set allowCaptionSafeBand=true only after explicit review", **common))
                operations.append({"trackId": track.id, "trackIndex": track_index, "clipIndex": clip_index,
                                   "clipId": clip.id, "source": clip.source, "cleanupIndex": cleanup_index,
                                   "mode": cleanup.mode, "region": {"x": cleanup.x, "y": cleanup.y, "width": cleanup.width, "height": cleanup.height},
                                   "clipTime": {"start": cleanup.start, "end": end},
                                   "timelineTime": {"start": clip.start + cleanup.start, "end": clip.start + end},
                                   "captionSafeBand": {"startY": safe_band_start, "endY": project.output.height,
                                                       "overlap": overlaps_safe_band, "explicitlyAllowed": cleanup.allow_caption_safe_band}})
    return issues, {"operationCount": len(operations), "captionSafeBand": {"startY": safe_band_start, "endY": project.output.height},
                    "operations": operations}


def validate_audio_safety(project: Project, ffmpeg: str | None) -> tuple[list[ValidationIssue], dict[str, Any]]:
    issues: list[ValidationIssue] = []
    policy = project.master_audio_policy
    has_audio = any(track.enabled and track.clips for track in project.audio_tracks)
    release_required = project.requires_master_audio_safety
    if release_required and policy is None:
        issues.append(ValidationIssue("MASTER_AUDIO_POLICY_REQUIRED", "error", "release output requires masterAudioPolicy", track_kind="audio"))
    if policy and (release_required or policy.required) and not policy.limiter and policy.loudness_target_lufs is None:
        issues.append(ValidationIssue("MASTER_AUDIO_LIMITER_REQUIRED", "error", "required master audio safety needs limiter or loudness normalization", track_kind="audio"))
    if not has_audio or (policy is None and not release_required):
        return issues, {"enabled": policy is not None, "required": release_required or bool(policy and policy.required),
                        "projected": None, "sourcePeaks": []}
    peak_cache: dict[str, float | None] = {}
    source_peaks = []
    clips = []
    for track_index, track in enumerate(project.audio_tracks):
        if not track.enabled:
            continue
        for clip_index, clip in enumerate(track.clips):
            if clip.source not in peak_cache:
                peak = None
                if ffmpeg:
                    measured = subprocess.run([ffmpeg, "-hide_banner", "-i", clip.source, "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
                    match = re.search(r"max_volume:\s*(-?inf|[-+0-9.]+) dB", measured.stderr)
                    if measured.returncode == 0 and match:
                        peak = -120.0 if match.group(1) == "-inf" else float(match.group(1))
                    else:
                        issues.append(ValidationIssue("AUDIO_PEAK_UNREADABLE", "error", "cannot measure source peak for gain projection",
                                                      track_id=track.id, track_kind="audio", track_index=track_index,
                                                      clip_index=clip_index, clip_id=clip.id, source=clip.source))
                peak_cache[clip.source] = peak
                source_peaks.append({"source": clip.source, "peakDbfs": peak})
            source_peak = peak_cache[clip.source]
            gain_db = 20 * math.log10(clip.volume) if clip.volume > 0 else -120.0
            projected = (source_peak + gain_db) if source_peak is not None else None
            clips.append({"clip": clip, "track": track, "trackIndex": track_index, "clipIndex": clip_index,
                          "sourcePeakDbfs": source_peak, "gainDb": gain_db, "projectedPeakDbfs": projected})
    events = sorted({time for item in clips for time in (item["clip"].start, item["clip"].start + item["clip"].duration)})
    worst = -120.0
    worst_time = 0.0
    worst_active: list[dict[str, Any]] = []
    for left, right in zip(events, events[1:]):
        if right <= left:
            continue
        middle = (left + right) / 2
        active = [item for item in clips if item["clip"].start <= middle < item["clip"].start + item["clip"].duration and item["projectedPeakDbfs"] is not None]
        amplitude = sum(10 ** (item["projectedPeakDbfs"] / 20) for item in active)
        combined = 20 * math.log10(amplitude) if amplitude > 0 else -120.0
        if combined > worst:
            worst, worst_time, worst_active = combined, left, active
    ceiling = policy.true_peak_ceiling_dbtp if policy else 0.0
    risk = worst > ceiling + 1e-6
    if risk:
        severity = "warning" if policy and (policy.limiter or policy.loudness_target_lufs is not None) else "error"
        issues.append(ValidationIssue("PROJECTED_AUDIO_CLIPPING_RISK", severity,
                                      f"worst-case summed peak is {worst:.2f} dBFS at {worst_time:.3f}s; ceiling is {ceiling:g} dBTP",
                                      track_kind="audio", time_range=_range(worst_time, worst_time),
                                      related_clips=[{"trackId": item["track"].id, "clipId": item["clip"].id,
                                                      "source": item["clip"].source, "sourcePeakDbfs": item["sourcePeakDbfs"],
                                                      "volume": item["clip"].volume, "gainDb": round(item["gainDb"], 3),
                                                      "projectedPeakDbfs": round(item["projectedPeakDbfs"], 3)} for item in worst_active]))
    return issues, {"enabled": policy is not None, "required": release_required or bool(policy and policy.required),
                    "policy": asdict(policy) if policy else None, "sourcePeaks": source_peaks,
                    "projected": {"worstCombinedPeakDbfs": round(worst, 3), "time": worst_time,
                                  "ceilingDbtp": ceiling, "risk": risk, "activeClipCount": len(worst_active)}}


def _values(metadata: dict[str, Any], *names: str) -> list[str]:
    value = next((metadata[name] for name in names if name in metadata), None)
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if isinstance(item, (str, int)) and str(item).strip()]


def validate_narrative(project: Project) -> tuple[list[ValidationIssue], dict[str, Any]]:
    policy = project.narrative_policy
    marked = any(any(key in clip.metadata for key in ("narrative_function", "new_information", "semantic_group", "fallback_only"))
                 for track in project.video_tracks if track.enabled for clip in track.clips)
    enabled = bool(policy.get("enabled", False) or project.runtime_policy or marked)
    if not enabled:
        return [], {"enabled": False}
    issues: list[ValidationIssue] = []
    coverage_gaps: list[dict[str, Any]] = []
    clips = [(ti, track, ci, clip) for ti, track in enumerate(project.video_tracks)
             if track.enabled for ci, clip in enumerate(track.clips) if clip.opacity > 0]
    semantic: dict[str, list[dict[str, Any]]] = {}
    known_context: set[str] = set()
    present_shots: set[str] = set()
    background_intervals: list[tuple[float, float]] = []
    background_roles = {"background", "bed", "atmosphere", "ambient", "establishing"}
    for track_index, track, clip_index, clip in clips:
        md = clip.metadata
        role = str(md.get("narrative_function", md.get("narrative_role", md.get("narrativeRole", "")))).strip().lower()
        semantic_ids = _values(md, "semantic_group", "semantic_id", "semanticId")
        information = _values(md, "new_information", "information_ids", "informationIds", "information_id", "informationId")
        shot_ids = _values(md, "shot_id", "shotId") or ([clip.id] if clip.id else [])
        present_shots.update(shot_ids)
        context = _values(md, "dialogue_id", "dialogueId", "beat_id", "beatId", "event_id", "eventId")
        known_context.update(information)
        known_context.update(context)
        common = dict(track_id=track.id, track_kind="video", track_index=track_index, clip_index=clip_index,
                      clip_id=clip.id, metadata=md or None, source=clip.source,
                      time_range=_range(clip.start, clip.start + clip.duration))
        missing_fields = [name for name, present in (("narrative_function", bool(role)), ("new_information", bool(information)),
                                                     ("semantic_group", bool(semantic_ids)), ("fallback_only", "fallback_only" in md)) if not present]
        if policy.get("requireMetadata", True) and missing_fields:
            issues.append(ValidationIssue("NARRATIVE_METADATA_REQUIRED", "error", f"video clip missing required narrative fields: {', '.join(missing_fields)}", **common))
            coverage_gaps.append({"code": "NARRATIVE_METADATA_REQUIRED", "clipId": clip.id, "dialogue_id": md.get("dialogue_id"), "required": missing_fields, "duration": clip.duration})
        for semantic_id in semantic_ids:
            semantic.setdefault(semantic_id, []).append({"trackId": track.id, "clipIndex": clip_index, "clipId": clip.id,
                                                         "timeRange": common["time_range"]})
        narrative_value = md.get("narrative_value", md.get("narrativeValue", True))
        if policy.get("rejectNoInformation", True) and (narrative_value is False or not (information or context)):
            issues.append(ValidationIssue("NARRATIVE_NO_NEW_INFORMATION", "error", "shot adds no declared information and is rejected", **common))
            coverage_gaps.append({"code": "NARRATIVE_NO_NEW_INFORMATION", "clipId": clip.id, "dialogue_id": md.get("dialogue_id"), "required": ["new_information"], "duration": clip.duration})
        if md.get("fallback_only") is True:
            issues.append(ValidationIssue("NARRATIVE_FALLBACK_FORBIDDEN", "error", "fallback_only material cannot enter a final timeline", **common))
            coverage_gaps.append({"code": "NARRATIVE_FALLBACK_FORBIDDEN", "clipId": clip.id, "dialogue_id": md.get("dialogue_id"), "required": ["non_fallback_asset"], "duration": clip.duration})
        if project.runtime_policy.get("paddingForbidden", False) and (md.get("padding") is True or role in {"padding", "generic_safe_bed", "generic_bed"}):
            issues.append(ValidationIssue("NARRATIVE_PADDING_FORBIDDEN", "error", "runtimePolicy.paddingForbidden=true rejects timeline padding", **common))
            coverage_gaps.append({"code": "NARRATIVE_PADDING_FORBIDDEN", "clipId": clip.id, "dialogue_id": md.get("dialogue_id"), "required": ["shorten or request_asset"], "duration": clip.duration})
        is_cutaway = role == "cutaway" or any(word in role for word in ("insert", "bridge", "cutaway"))
        if is_cutaway and policy.get("requireCutawayRelevance", True):
            relevance = _values(md, "relevance_to", "relevanceTo")
            score = md.get("relevance_score", md.get("relevanceScore"))
            minimum = float(policy.get("minCutawayRelevance", 0.5))
            # Existing production projects bind motivated inserts to the active
            # beat plus an explicit information gain. New projects should use
            # relevance_to; both forms are deterministic and auditable.
            implicitly_relevant = bool(md.get("beat_id") and information)
            if (not relevance and not implicitly_relevant) or (score is not None and (not isinstance(score, (int, float)) or score < minimum)):
                issues.append(ValidationIssue("CUTAWAY_NOT_RELEVANT", "error", "cutaway does not answer an active dialogue/beat question", **common))
                coverage_gaps.append({"code": "CUTAWAY_NOT_RELEVANT", "clipId": clip.id, "dialogue_id": md.get("dialogue_id"), "required": ["relevance_to"], "duration": clip.duration})
        if role == "reaction_delta":
            emotion_before, emotion_after = md.get("emotion_before"), md.get("emotion_after")
            power_before, power_after = md.get("power_before"), md.get("power_after")
            has_delta = ((emotion_before is not None and emotion_after is not None and emotion_before != emotion_after) or
                         (power_before is not None and power_after is not None and power_before != power_after))
            if not has_delta or str(md.get("reaction_type", "")).lower() == "neutral_hold":
                issues.append(ValidationIssue("REACTION_DELTA_REQUIRED", "error", "reaction shot requires a changed emotion or power state; neutral_hold is forbidden", **common))
                coverage_gaps.append({"code": "REACTION_DELTA_REQUIRED", "clipId": clip.id, "dialogue_id": md.get("dialogue_id"), "required": ["emotion_before!=emotion_after or power_before!=power_after"], "duration": clip.duration})
        is_background = role in background_roles or "background" in role or role == "generic_bed"
        if is_background:
            background_intervals.append((clip.start, clip.start + clip.duration))
            maximum = float(policy.get("maxBackgroundBedSeconds", 2.0))
            if clip.duration > maximum + 1e-6:
                issues.append(ValidationIssue("BACKGROUND_BED_CLIP_BUDGET_EXCEEDED", "error", f"background shot duration {clip.duration:g}s exceeds {maximum:g}s", **common))
            if md.get("covers_critical_clue") is True or md.get("coversCriticalClue") is True:
                issues.append(ValidationIssue("BACKGROUND_BED_COVERS_CRITICAL_CLUE", "error", "background bed cannot cover critical-clue dialogue", **common))
    maximum_repeats = int(policy.get("maxSemanticRepeats", 1))
    if policy.get("rejectDuplicateSemantics", False) or "maxSemanticRepeats" in policy:
        for semantic_id, related in semantic.items():
            if len(related) > maximum_repeats:
                issues.append(ValidationIssue("NARRATIVE_SEMANTIC_DUPLICATE", "error", f"semantic_id {semantic_id!r} appears {len(related)} times (max {maximum_repeats})", track_kind="video", related_clips=related))
    # Relevance targets are checked after collecting all clip context, so order
    # does not matter and agents can reference a later dialogue/beat.
    for track_index, track, clip_index, clip in clips:
        md = clip.metadata
        role = str(md.get("narrative_function", md.get("narrative_role", md.get("narrativeRole", "")))).strip().lower()
        relevance = _values(md, "relevance_to", "relevanceTo")
        if (role == "cutaway" or any(word in role for word in ("insert", "bridge", "cutaway"))) and relevance and not set(relevance).intersection(known_context):
            issues.append(ValidationIssue("CUTAWAY_CONTEXT_MISMATCH", "error", "cutaway relevance_to does not match any dialogue, beat, event, or information id", track_id=track.id, track_kind="video", track_index=track_index, clip_index=clip_index, clip_id=clip.id, metadata=md, source=clip.source, time_range=_range(clip.start, clip.start + clip.duration)))
    background_seconds = sum(end - start for start, end in _merge(background_intervals))
    background_ratio = background_seconds / project.main_duration if project.main_duration else 0
    max_ratio = float(policy.get("maxBackgroundBedRatio", 0.1))
    if background_ratio > max_ratio + 1e-6:
        issues.append(ValidationIssue("BACKGROUND_BED_BUDGET_EXCEEDED", "error", f"background bed uses {background_ratio:.1%} of movie (max {max_ratio:.1%})", track_kind="video"))
    required = list(policy.get("requiredShotIds", []))
    missing = [shot_id for shot_id in required if shot_id not in present_shots]
    if missing:
        issues.append(ValidationIssue("REQUIRED_SHOTS_MISSING", "error", f"required shots are missing: {', '.join(missing)}", track_kind="video"))
        coverage_gaps.extend({"code": "NARRATIVE_COVERAGE_GAP", "dialogue_id": None, "required": [shot_id], "duration": None} for shot_id in missing)

    # CL2X-282 stagnation and semantic cooldown operate on chronological main
    # shots. Overlay clips do not reset the sequence.
    ordered = sorted(clips, key=lambda item: (item[3].start, item[0], item[2]))
    for left, right in zip(ordered, ordered[1:]):
        def background(item: tuple[Any, Any, Any, Any]) -> bool:
            value = str(item[3].metadata.get("narrative_function", item[3].metadata.get("narrative_role", ""))).lower()
            return value in background_roles or "background" in value or value in {"generic_bed", "generic_safe_bed"}
        if background(left) and background(right):
            issues.append(ValidationIssue("BACKGROUND_BED_CONSECUTIVE", "error", "two background-bed shots cannot be consecutive", track_kind="video", related_clips=[{"clipId": left[3].id}, {"clipId": right[3].id}]))
    no_info_run: list[tuple[Any, Any, Any, Any]] = []
    for item in ordered:
        info = _values(item[3].metadata, "new_information", "information_ids", "informationIds", "information_id", "informationId")
        if info:
            no_info_run = []
        else:
            no_info_run.append(item)
            if len(no_info_run) == 2:
                related = [{"trackId": x[1].id, "clipIndex": x[2], "clipId": x[3].id,
                            "timeRange": _range(x[3].start, x[3].start + x[3].duration)} for x in no_info_run]
                issues.append(ValidationIssue("NARRATIVE_STAGNATION", "error", "two consecutive shots add no new information", track_kind="video", related_clips=related))
    semantic_entries: dict[str, list[tuple[float, float, Clip, Track, int]]] = {}
    for _ti, track, ci, clip in ordered:
        for group in _values(clip.metadata, "semantic_group", "semantic_id", "semanticId"):
            semantic_entries.setdefault(group, []).append((clip.start, clip.start + clip.duration, clip, track, ci))
    semantic_duration: dict[str, float] = {}
    max_semantic_group_ratio = float(policy.get("maxSemanticGroupRatio", 0.15))
    budget_evaluated_groups: list[str] = []
    budget_single_use_groups: list[str] = []
    for group, entries in semantic_entries.items():
        semantic_duration[group] = sum(b - a for a, b in _merge([(x[0], x[1]) for x in entries]))
        pct = semantic_duration[group] / project.main_duration if project.main_duration else 0
        for left, right in zip(entries, entries[1:]):
            if right[0] <= left[1] + 1e-6:
                issues.append(ValidationIssue("SEMANTIC_COOLDOWN_CONSECUTIVE", "error", f"semantic_group {group!r} is used in consecutive shots", track_kind="video", related_clips=[{"clipId": left[2].id}, {"clipId": right[2].id}]))
        for start_i in range(len(entries)):
            in_window = [x for x in entries if entries[start_i][0] <= x[0] < entries[start_i][0] + 12]
            if len(in_window) > 2:
                issues.append(ValidationIssue("SEMANTIC_COOLDOWN_12S", "error", f"semantic_group {group!r} occurs {len(in_window)} times within 12s (max 2)", track_kind="video", related_clips=[{"clipId": x[2].id} for x in in_window]))
                break
        # This budget is a repetition guard, not a minimum project-length gate.
        # A semantic group used once cannot be repetitive, and short segments
        # naturally give every unique shot a ratio greater than 15%.
        if len(entries) == 1:
            budget_single_use_groups.append(group)
        else:
            budget_evaluated_groups.append(group)
            if pct > max_semantic_group_ratio + 1e-6:
                issues.append(ValidationIssue(
                    "SEMANTIC_GLOBAL_BUDGET_EXCEEDED", "error",
                    f"repeated semantic_group {group!r} occupies {pct:.1%} of movie (max {max_semantic_group_ratio:.1%})",
                    track_kind="video", related_clips=[{"clipId": x[2].id} for x in entries],
                ))
    on_gap = project.runtime_policy.get("onCoverageGap", "fail")
    padding_forbidden = bool(project.runtime_policy.get("paddingForbidden", False))
    if coverage_gaps and on_gap == "fail":
        issues.append(ValidationIssue("NARRATIVE_COVERAGE_GAP", "error", f"{len(coverage_gaps)} narrative coverage gaps; runtimePolicy.onCoverageGap=fail", track_kind="video"))
    return issues, {"enabled": True, "policySource": "narrativeGate" if policy else "runtimePolicy/metadata",
                    "runtimePolicy": {"allowShorter": bool(project.runtime_policy.get("allowShorter", False)),
                                      "paddingForbidden": padding_forbidden, "onCoverageGap": on_gap},
                    "coverageGaps": coverage_gaps, "semanticCounts": {k: len(v) for k, v in semantic.items()},
                    "semanticDurationRatio": {k: (v / project.main_duration if project.main_duration else 0) for k, v in semantic_duration.items()},
                    "semanticBudget": {"mode": "repeated-groups-only", "maxGroupRatio": max_semantic_group_ratio,
                                       "evaluatedGroups": sorted(budget_evaluated_groups),
                                       "singleUseGroups": sorted(budget_single_use_groups)},
                    "backgroundBedSeconds": background_seconds, "backgroundBedRatio": background_ratio,
                    "requiredShotIds": required, "presentShotIds": sorted(present_shots), "missingShotIds": missing}


CUT_REASON_FIELDS = ("scene_id", "light_key", "axis_line", "eyeline")


def validate_cut_reason_contract(project: Project) -> tuple[list[ValidationIssue], dict[str, Any]]:
    """Reject video clips without the compiler's explicit cut contract."""
    if not project.require_cut_reason:
        return [], {"required": False, "cuts": [], "missing": []}
    reasons: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    issues: list[ValidationIssue] = []
    for track_index, track in enumerate(project.video_tracks):
        if not track.enabled:
            continue
        for clip_index, clip in enumerate(track.clips):
            metadata = dict(clip.metadata or {})
            record = {
                "trackId": track.id,
                "trackIndex": track_index,
                "clipIndex": clip_index,
                "clipId": clip.id,
                "cutReason": metadata.get("cut_reason"),
                "continuity": {field: metadata.get(field) for field in CUT_REASON_FIELDS},
            }
            reasons.append(record)
            missing_fields = [field for field in ("cut_reason", *CUT_REASON_FIELDS) if not metadata.get(field)]
            if missing_fields:
                missing.append({**record, "missingFields": missing_fields})
                issues.append(ValidationIssue(
                    "CUT_REASON_REQUIRED", "error",
                    "requireCutReason=true requires cut_reason and scene_id/light_key/axis_line/eyeline",
                    track_id=track.id, track_kind="video", track_index=track_index,
                    clip_index=clip_index, clip_id=clip.id, metadata=metadata,
                    source=clip.source, time_range=_range(clip.start, clip.start + clip.duration),
                ))
    return issues, {"required": True, "cuts": reasons, "missing": missing}


def validate_source_admission(project: Project) -> tuple[list[ValidationIssue], dict[str, Any]]:
    policy = dict(project.source_admission_policy or {})
    video_clips = [
        (track_index, clip_index, track, clip)
        for track_index, track in enumerate(project.video_tracks) if track.enabled
        for clip_index, clip in enumerate(track.clips)
    ]
    metadata_opt_in = any(
        any(key in clip.metadata for key in ("action_required", "action_trajectory", "source_reference_mode", "cadence_report_path"))
        for _ti, _ci, _track, clip in video_clips
    )
    # Legacy release projects remain renderable, but the new release contract
    # activates this gate whenever releaseGate.required, an explicit policy,
    # or per-shot admission metadata is present.
    enabled = bool(policy.get("enabled", False) or project.release_gate.get("required", False) or metadata_opt_in)
    threshold = float(policy.get("maxActionNearDuplicateRatio", 0.15))
    require_cadence = bool(policy.get("requirePerShotCadence", True))
    require_trajectory = bool(policy.get("requireActionTrajectory", True))
    still_mode = str(policy.get("singleStillAction", "block"))
    rough_mode = project.assembly_mode == "NON_RELEASE_ROUGH_ASSEMBLY"
    legacy_rough = bool(policy.get("roughAssemblyException"))
    allow_conditional = bool(policy.get("allowConditionalCadenceFailForRoughAssembly", legacy_rough))
    release_designated = bool(
        project.release_project or project.release_gate.get("required", False) or
        project.metadata.get("releaseAllowed") is True or project.metadata.get("platformUploadAllowed") is True or
        project.qingshan_audit.get("final") is True or project.qingshan_audit.get("platformUploadAllowed") is True
    )
    rough_contract_valid = rough_mode and allow_conditional and not release_designated
    configured_allowed_failures = policy.get("allowedConditionalFailureCodes")
    allowed_conditional_failures = set(
        ["video.periodic_duplicate", "audio.long_silence"]
        if configured_allowed_failures is None else configured_allowed_failures
    )

    def digest(path: str | Path) -> str:
        value = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(chunk)
        return value.hexdigest()

    conditional_clips = [clip for _ti, _ci, _track, clip in video_clips
                         if str(clip.metadata.get("source_admission") or "") == "CONDITIONAL_MACHINE_ADMISSION"]
    evidence_path = policy.get("conditionalAdmissionEvidencePath")
    evidence_path_source = "project_policy"
    if not evidence_path and legacy_rough and conditional_clips:
        candidates = set()
        for clip in conditional_clips:
            raw_path = clip.metadata.get("ocr_report_path")
            if isinstance(raw_path, str) and raw_path.endswith("_AI_REVIEW_RESULT.json"):
                candidates.add(raw_path[:-len("_AI_REVIEW_RESULT.json")] + "_CONDITIONAL_ADMISSION.json")
        if len(candidates) == 1:
            evidence_path = candidates.pop()
            evidence_path_source = "legacy_raw_review_sibling"
    evidence: dict[str, Any] | None = None
    evidence_items: dict[str, dict[str, Any]] = {}
    raw_review_items_by_path: dict[str, dict[str, Any]] = {}
    evidence_global_reasons: list[str] = []
    evidence_sha: str | None = None
    if conditional_clips and rough_mode:
        if not evidence_path:
            evidence_global_reasons.append("conditional_admission_evidence_missing")
        else:
            try:
                evidence_file = Path(str(evidence_path)).resolve()
                with evidence_file.open(encoding="utf-8") as stream:
                    loaded = json.load(stream)
                if not isinstance(loaded, dict):
                    raise ValueError("conditional admission evidence is not an object")
                evidence = loaded
                evidence_sha = digest(evidence_file)
                if evidence.get("schema") != "qingshan.conditional_machine_admission.v1":
                    evidence_global_reasons.append("conditional_admission_schema_invalid")
                raw_review = evidence.get("raw_review")
                raw_review_sha = evidence.get("raw_review_sha256")
                if not isinstance(raw_review, str) or not isinstance(raw_review_sha, str):
                    evidence_global_reasons.append("conditional_raw_review_provenance_missing")
                else:
                    try:
                        raw_review_file = Path(raw_review).resolve()
                        if digest(raw_review_file) != raw_review_sha.lower():
                            evidence_global_reasons.append("conditional_raw_review_sha_mismatch")
                        with raw_review_file.open(encoding="utf-8") as stream:
                            raw_review_value = json.load(stream)
                        raw_review_items = raw_review_value.get("items") if isinstance(raw_review_value, dict) else None
                        if not isinstance(raw_review_items, list):
                            evidence_global_reasons.append("conditional_raw_review_items_missing")
                        else:
                            for raw_item in raw_review_items:
                                raw_media_path = raw_item.get("media_path") if isinstance(raw_item, dict) else None
                                if isinstance(raw_media_path, str) and raw_media_path:
                                    resolved_raw_path = str(Path(raw_media_path).resolve())
                                    if resolved_raw_path in raw_review_items_by_path:
                                        evidence_global_reasons.append("conditional_raw_review_duplicate_media_path")
                                    raw_review_items_by_path[resolved_raw_path] = raw_item
                    except OSError:
                        evidence_global_reasons.append("conditional_raw_review_unreadable")
                    except (ValueError, json.JSONDecodeError):
                        evidence_global_reasons.append("conditional_raw_review_invalid")
                raw_items = evidence.get("items")
                if not isinstance(raw_items, list):
                    evidence_global_reasons.append("conditional_admission_items_missing")
                else:
                    for item in raw_items:
                        if isinstance(item, dict) and isinstance(item.get("unit_id"), str):
                            if item["unit_id"] in evidence_items:
                                evidence_global_reasons.append(f"conditional_admission_duplicate_unit:{item['unit_id']}")
                            evidence_items[item["unit_id"]] = item
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                evidence_global_reasons.append(f"conditional_admission_evidence_unreadable:{type(exc).__name__}")
    if not enabled:
        return [], {
            "enabled": False, "admittedCandidateCount": len(video_clips), "checkedCandidateCount": 0,
            "blockedCandidateCount": 0, "conditionalSourceCount": 0,
            "automaticPlatformReplacementAllowed": False,
        }
    issues: list[ValidationIssue] = []
    items: list[dict[str, Any]] = []
    conditional_count = 0
    for track_index, clip_index, track, clip in video_clips:
        metadata = dict(clip.metadata or {})
        shot_id = str(metadata.get("shot_id") or metadata.get("source_id") or clip.id or f"clip-{clip_index}")
        action_required = metadata.get("action_required")
        trajectory = metadata.get("action_trajectory")
        reference_mode = metadata.get("source_reference_mode")
        admission = str(metadata.get("source_admission") or "UNSPECIFIED")
        if admission == "CONDITIONAL_MACHINE_ADMISSION":
            conditional_count += 1
        reasons: list[str] = []
        warnings: list[str] = []
        cadence_status: str | None = None
        near_duplicate_ratio: float | None = None
        report_video: str | None = None
        report_path = metadata.get("cadence_report_path")
        if not isinstance(action_required, bool):
            reasons.append("action_required_missing")
        if not isinstance(reference_mode, str) or not reference_mode:
            reasons.append("source_reference_mode_missing")
        if action_required is True and require_trajectory:
            missing = [name for name in ("windup", "contact", "force", "result") if not isinstance(trajectory, dict) or not str(trajectory.get(name) or "").strip()]
            if missing:
                reasons.append("action_trajectory_incomplete:" + ",".join(missing))
        if action_required is True and reference_mode == "single_still_only":
            if still_mode == "block":
                reasons.append("single_still_only_cannot_prove_required_action")
            else:
                warnings.append("single_still_only_for_required_action")
        if require_cadence and (not isinstance(report_path, str) or not report_path.strip()):
            reasons.append("per_shot_cadence_report_missing")
        elif isinstance(report_path, str) and report_path.strip():
            try:
                with Path(report_path).open(encoding="utf-8") as stream:
                    report = json.load(stream)
                if not isinstance(report, dict):
                    raise ValueError("cadence report is not an object")
                cadence_status = str(report.get("status") or "").upper()
                periodic = report.get("periodic_duplicates") if isinstance(report.get("periodic_duplicates"), dict) else {}
                raw_ratio = report.get("near_duplicate_ratio", periodic.get("near_duplicate_ratio"))
                if isinstance(raw_ratio, bool) or not isinstance(raw_ratio, (int, float)):
                    reasons.append("near_duplicate_ratio_missing")
                else:
                    near_duplicate_ratio = float(raw_ratio)
                    if not 0 <= near_duplicate_ratio <= 1:
                        reasons.append("near_duplicate_ratio_out_of_range")
                report_video = str(report.get("video") or "") or None
                if report_video and Path(report_video).resolve() != Path(clip.source).resolve():
                    reasons.append("cadence_report_source_mismatch")
                if cadence_status != "PASS":
                    reasons.append("cadence_fail")
                if action_required is True and near_duplicate_ratio is not None and near_duplicate_ratio > threshold + 1e-12:
                    reasons.append(f"action_near_duplicate_ratio_exceeded:{near_duplicate_ratio:.9f}>{threshold:.9f}")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                reasons.append(f"per_shot_cadence_report_unreadable:{type(exc).__name__}")
        conditional_evidence: dict[str, Any] | None = None
        conditional_evidence_reasons: list[str] = []
        if admission == "CONDITIONAL_MACHINE_ADMISSION":
            unit_id = str(metadata.get("unit_id") or metadata.get("source_id") or shot_id)
            conditional_evidence_reasons.extend(evidence_global_reasons)
            evidence_item = evidence_items.get(unit_id)
            if not rough_contract_valid:
                conditional_evidence_reasons.append("conditional_source_requires_non_release_rough_assembly")
            if evidence_item is None:
                conditional_evidence_reasons.append("conditional_admission_item_missing")
            else:
                candidate_path = evidence_item.get("candidate_path")
                candidate_sha = evidence_item.get("candidate_sha256")
                raw_failures = evidence_item.get("raw_failures")
                confidence = evidence_item.get("confidence")
                if evidence_item.get("decision") != "CONDITIONAL_MACHINE_ADMISSION":
                    conditional_evidence_reasons.append("conditional_decision_mismatch")
                if not isinstance(candidate_path, str) or Path(candidate_path).resolve() != Path(clip.source).resolve():
                    conditional_evidence_reasons.append("conditional_candidate_path_mismatch")
                if not isinstance(candidate_sha, str) or len(candidate_sha) != 64:
                    conditional_evidence_reasons.append("conditional_candidate_sha_missing")
                else:
                    metadata_sha = metadata.get("source_sha256")
                    if metadata_sha != candidate_sha:
                        conditional_evidence_reasons.append("conditional_metadata_sha_mismatch")
                    try:
                        actual_sha = digest(clip.source)
                        if actual_sha != candidate_sha.lower():
                            conditional_evidence_reasons.append("conditional_actual_source_sha_mismatch")
                    except OSError:
                        conditional_evidence_reasons.append("conditional_source_unreadable")
                if not isinstance(raw_failures, list) or not raw_failures or any(not isinstance(x, str) or not x for x in raw_failures):
                    conditional_evidence_reasons.append("conditional_raw_failures_missing")
                    raw_failures = []
                disallowed = sorted(set(raw_failures) - allowed_conditional_failures)
                if disallowed:
                    conditional_evidence_reasons.append("conditional_failure_not_rough_eligible:" + ",".join(disallowed))
                if evidence_item.get("raw_qa_status") != "FAIL":
                    conditional_evidence_reasons.append("conditional_raw_fail_status_not_preserved")
                raw_review_item = raw_review_items_by_path.get(str(Path(clip.source).resolve()))
                if raw_review_item is None:
                    conditional_evidence_reasons.append("conditional_raw_review_item_missing")
                else:
                    if raw_review_item.get("media_sha256") != candidate_sha:
                        conditional_evidence_reasons.append("conditional_raw_review_candidate_sha_mismatch")
                    if raw_review_item.get("status") != evidence_item.get("raw_qa_status"):
                        conditional_evidence_reasons.append("conditional_raw_review_status_mismatch")
                    raw_blocking_failures = [
                        issue.get("rule_id") for issue in raw_review_item.get("issues", [])
                        if isinstance(issue, dict) and issue.get("blocking") is True and isinstance(issue.get("rule_id"), str)
                    ] if isinstance(raw_review_item.get("issues"), list) else []
                    if not raw_blocking_failures:
                        required_failures = raw_review_item.get("required_capability_failures")
                        if isinstance(required_failures, list):
                            raw_blocking_failures = [value for value in required_failures if isinstance(value, str)]
                    if sorted(raw_blocking_failures) != sorted(raw_failures):
                        conditional_evidence_reasons.append("conditional_raw_review_failures_mismatch")
                if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                    conditional_evidence_reasons.append("conditional_confidence_invalid")
                for field in ("selection_reason", "rollback_point", "replacement_condition"):
                    if not isinstance(evidence_item.get(field), str) or not evidence_item[field].strip():
                        conditional_evidence_reasons.append(f"conditional_{field}_missing")
                conditional_evidence = {
                    "path": str(evidence_path) if evidence_path else None,
                    "sha256": evidence_sha, "pathSource": evidence_path_source,
                    "unitId": unit_id, "candidateSha256": candidate_sha,
                    "rawQaStatus": evidence_item.get("raw_qa_status"), "rawFailures": raw_failures,
                    "decision": evidence_item.get("decision"), "confidence": confidence,
                    "selectionReason": evidence_item.get("selection_reason"),
                    "rollbackPoint": evidence_item.get("rollback_point"),
                    "replacementCondition": evidence_item.get("replacement_condition"),
                }
            suppressible = {
                reason for reason in reasons
                if reason == "cadence_fail" or reason.startswith("action_near_duplicate_ratio_exceeded:")
            }
            if not conditional_evidence_reasons and rough_contract_valid:
                reasons = [reason for reason in reasons if reason not in suppressible]
                warnings.extend(["original_" + reason for reason in sorted(suppressible)])
                warnings.append("conditional_source_non_release_rough_assembly_only")
            else:
                reasons.extend(conditional_evidence_reasons)
        blocked = bool(reasons)
        item = {
            "shotId": shot_id, "clipId": clip.id, "source": clip.source,
            "actionRequired": action_required, "actionTrajectory": trajectory,
            "sourceReferenceMode": reference_mode, "sourceAdmission": admission,
            "cadenceReportPath": report_path, "cadenceReportVideo": report_video,
            "cadenceStatus": cadence_status, "nearDuplicateRatio": near_duplicate_ratio,
            "nearDuplicateThreshold": threshold if action_required is True else None,
            "status": "BLOCK_AGENTCUT_ASSEMBLY" if blocked else "PASS",
            "reasons": reasons, "warnings": warnings,
            "conditionalEvidence": conditional_evidence,
            "releaseEligible": admission != "CONDITIONAL_MACHINE_ADMISSION",
        }
        if not blocked and admission == "CONDITIONAL_MACHINE_ADMISSION":
            item["status"] = "PASS_CONDITIONAL_NON_RELEASE_ROUGH_ASSEMBLY"
        items.append(item)
        if blocked:
            issues.append(ValidationIssue(
                "BLOCK_AGENTCUT_ASSEMBLY", "error", f"{shot_id}: " + "; ".join(reasons),
                track_id=track.id, track_kind="video", track_index=track_index,
                clip_index=clip_index, clip_id=clip.id, metadata=metadata,
                source=clip.source, time_range=_range(clip.start, clip.start + clip.duration),
            ))
        for warning in warnings:
            issues.append(ValidationIssue(
                "SOURCE_ADMISSION_WARNING", "warning", f"{shot_id}: {warning}",
                track_id=track.id, track_kind="video", track_index=track_index,
                clip_index=clip_index, clip_id=clip.id, metadata=metadata, source=clip.source,
            ))
    blocked_count = sum(item["status"] == "BLOCK_AGENTCUT_ASSEMBLY" for item in items)
    conditional_admitted = sum(item["status"] == "PASS_CONDITIONAL_NON_RELEASE_ROUGH_ASSEMBLY" for item in items)
    return issues, {
        "enabled": True, "requirePerShotCadence": require_cadence,
        "maxActionNearDuplicateRatio": threshold, "singleStillAction": still_mode,
        "admittedCandidateCount": len(items), "checkedCandidateCount": len(items),
        "blockedCandidateCount": blocked_count, "conditionalSourceCount": conditional_count,
        "status": "BLOCK_AGENTCUT_ASSEMBLY" if blocked_count else (
            "PASS_NON_RELEASE_ROUGH_ASSEMBLY" if conditional_admitted else "PASS"
        ),
        "assemblyMode": project.assembly_mode,
        "roughAssemblyEligible": bool(not blocked_count and rough_mode),
        "releaseEligible": not conditional_count and not project.hold_slots,
        "conditionalEvidencePath": str(evidence_path) if evidence_path else None,
        "conditionalEvidenceSha256": evidence_sha,
        "conditionallyAdmittedCount": conditional_admitted,
        "originalCadenceFailuresPreserved": True,
        "items": items,
        "conditionalMachineAdmissionTriggersPlatformReplacement": False,
        "automaticPlatformReplacementAllowed": False,
    }


def validate_release_gate(project: Project, source_coverage: dict[str, Any]) -> tuple[list[ValidationIssue], dict[str, Any]]:
    required = bool(project.release_project or project.release_gate.get("required", False))
    review_path = project.release_gate.get("fullCutVisualReviewPath")
    conditional_count = int(source_coverage.get("conditionalSourceCount") or 0)
    output = Path(project.output.path)
    if review_path and output.is_file():
        result = validate_release_output(output, review_path, conditional_source_count=conditional_count)
        return [], {"required": required, **result}
    return [], {
        "required": required,
        "status": "PENDING_POST_RENDER_VISUAL_REVIEW" if required else "NOT_REQUESTED",
        "cleanRelease": False,
        "final": str(output),
        "finalSha256": None,
        "reviewPath": review_path,
        "hardGatePassed": False,
        "conditionalSourceCount": conditional_count,
        "conditionalMachineAdmissionTriggersPlatformReplacement": False,
        "automaticPlatformReplacementAllowed": False,
        "platformMutationAuthorized": False,
        "nextAction": "run release-validate against current final SHA" if required else None,
    }


def validate_hold_slots(project: Project) -> tuple[list[ValidationIssue], dict[str, Any]]:
    issues: list[ValidationIssue] = []
    release_designated = bool(
        project.release_project or project.release_gate.get("required", False) or
        project.metadata.get("releaseAllowed") is True or project.metadata.get("platformUploadAllowed") is True or
        project.qingshan_audit.get("final") is True or project.qingshan_audit.get("platformUploadAllowed") is True
    )
    visible = [
        (clip.start, clip.start + clip.duration, clip.id, track.id)
        for track in project.video_tracks if track.enabled
        for clip in track.clips if clip.opacity > 0
    ]
    items = []
    for index, slot in enumerate(project.hold_slots):
        overlaps = [
            {"clipId": clip_id, "trackId": track_id, "timeRange": _range(start, end)}
            for start, end, clip_id, track_id in visible
            if start < slot.end - 1e-6 and end > slot.start + 1e-6
        ]
        if overlaps:
            issues.append(ValidationIssue(
                "HOLD_SLOT_OVERLAPS_VIDEO", "error",
                f"hold slot {slot.id} overlaps visible video; placeholders must reserve an actually empty interval",
                clip_id=slot.id, time_range=_range(slot.start, slot.end), related_clips=overlaps,
            ))
        if project.assembly_mode != "NON_RELEASE_ROUGH_ASSEMBLY":
            issues.append(ValidationIssue(
                "HOLD_SLOT_REQUIRES_ROUGH_ASSEMBLY", "error",
                f"hold slot {slot.id} is allowed only in NON_RELEASE_ROUGH_ASSEMBLY",
                clip_id=slot.id, time_range=_range(slot.start, slot.end),
            ))
        if release_designated:
            issues.append(ValidationIssue(
                "UNRESOLVED_HOLD_BLOCKS_RELEASE", "error",
                f"hold slot {slot.id} must be replaced before final/release validation",
                clip_id=slot.id, time_range=_range(slot.start, slot.end),
            ))
        else:
            issues.append(ValidationIssue(
                "UNRESOLVED_HOLD_NON_RELEASE_ONLY", "warning",
                f"hold slot {slot.id} preserves runtime but makes this output non-releasable",
                clip_id=slot.id, time_range=_range(slot.start, slot.end),
            ))
        items.append({
            "id": slot.id, "start": slot.start, "end": slot.end, "duration": slot.duration,
            "mode": slot.mode, "reason": slot.reason,
            "replacementCondition": slot.replacement_condition,
            "releaseBlocking": True, "overlapsVisibleVideo": bool(overlaps),
        })
    return issues, {
        "count": len(items), "unresolvedCount": len(items), "releaseEligible": not items,
        "assemblyMode": project.assembly_mode, "items": items,
        "renderBehavior": "timeline background is intentionally retained for each slot",
        "platformMutationAuthorized": False,
    }


def validate_shot_recipes(project: Project) -> tuple[list[ValidationIssue], dict[str, Any]]:
    problems, coverage = validate_and_materialize_shot_recipes(project)
    issues = [ValidationIssue(
        item.code, "error", item.message,
        track_id=item.track_id, track_kind="video" if item.track_id else None,
        track_index=item.track_index, clip_index=item.clip_index, clip_id=item.clip_id,
        metadata={
            "recipe_id": item.recipe_id, "recipe_phase": item.phase_id,
            "repairLocator": {"clipId": item.clip_id, "phaseId": item.phase_id},
        },
        time_range=item.time_range, related_clips=item.related_clips,
    ) for item in problems]
    return issues, coverage


class MediaValidator:
    def __init__(self, ffprobe: str, workers: int | None = None) -> None:
        self.ffprobe = ffprobe
        self.workers = workers or min(8, os.cpu_count() or 1)

    def _probe(self, source: str) -> dict[str, Any]:
        if shutil.which(self.ffprobe) is None:
            raise AgentCutError(f"FFprobe executable not found: {self.ffprobe}")
        process = subprocess.run([
            self.ffprobe, "-v", "error", "-show_entries",
            "format=duration,format_name:stream=index,codec_type,codec_name,duration,width,height,sample_rate",
            "-of", "json", source,
        ], capture_output=True, text=True)
        if process.returncode != 0:
            raise AgentCutError(process.stderr.strip() or "FFprobe failed")
        return json.loads(process.stdout)

    @staticmethod
    def _duration(probe: dict[str, Any], kind: str | None = None) -> float | None:
        def numbers(candidates: list[Any]) -> list[float]:
            values = []
            for value in candidates:
                try:
                    if value is not None:
                        values.append(float(value))
                except (TypeError, ValueError):
                    pass
            return values
        streams = probe.get("streams", [])
        selected = [x.get("duration") for x in streams if kind is None or x.get("codec_type") == kind]
        stream_values = numbers(selected)
        if stream_values:
            return max(stream_values)
        format_values = numbers([probe.get("format", {}).get("duration")])
        if format_values:
            return max(format_values)
        values = numbers([x.get("duration") for x in streams])
        return max(values) if values else None

    def validate(self, project: Project) -> ValidationReport:
        release_contract_issues, release_contract_coverage = validate_release_project_contract(project)
        replacement_issues, replacement_coverage = validate_replacement_bindings(project)
        subtitle_issues, subtitle_coverage = validate_subtitles(project)
        narrative_issues, narrative_coverage = validate_narrative(project)
        cut_reason_issues, cut_reason_coverage = validate_cut_reason_contract(project)
        outro_issues, outro_coverage = validate_outro(project, self.ffprobe.replace("ffprobe", "ffmpeg"))
        cleanup_issues, cleanup_coverage = validate_cleanup_regions(project)
        audio_issues, audio_coverage = validate_audio_safety(project, self.ffprobe.replace("ffprobe", "ffmpeg"))
        source_issues, source_coverage = validate_source_admission(project)
        release_issues, release_coverage = validate_release_gate(project, source_coverage)
        hold_issues, hold_coverage = validate_hold_slots(project)
        recipe_issues, recipe_coverage = validate_shot_recipes(project)
        issues: list[ValidationIssue] = [
            *release_contract_issues, *replacement_issues, *subtitle_issues, *narrative_issues, *cut_reason_issues, *outro_issues,
            *cleanup_issues, *audio_issues, *source_issues, *release_issues, *hold_issues, *recipe_issues,
        ]
        media: dict[str, dict[str, Any]] = {}
        probe_cache: dict[str, dict[str, Any] | Exception] = {}
        all_tracks = (("video", project.video_tracks), ("audio", project.audio_tracks))
        sources = list(dict.fromkeys(
            clip.source for _kind, tracks in all_tracks for track in tracks if track.enabled for clip in track.clips
        ))
        with ThreadPoolExecutor(max_workers=min(self.workers, len(sources) or 1), thread_name_prefix="ffprobe") as pool:
            futures = {pool.submit(self._probe, source): source for source in sources}
            for future in as_completed(futures):
                source = futures[future]
                try:
                    probe_cache[source] = future.result()
                except Exception as exc:
                    probe_cache[source] = exc
        for kind, tracks in all_tracks:
            for track_index, track in enumerate(tracks):
                if not track.enabled:
                    continue
                for clip_index, clip in enumerate(track.clips):
                    common = dict(
                        track_id=track.id, track_kind=kind, track_index=track_index, clip_index=clip_index,
                        clip_id=clip.id, metadata=clip.metadata or None, source=clip.source,
                        time_range=_range(clip.start, clip.start + clip.duration),
                        source_range=_range(clip.in_point, clip.in_point + clip.duration),
                    )
                    probe = probe_cache[clip.source]
                    if isinstance(probe, Exception):
                        issues.append(ValidationIssue("MEDIA_UNREADABLE", "error", str(probe), **common))
                        continue
                    streams = probe.get("streams", [])
                    duration = self._duration(probe)
                    stream_duration = self._duration(probe, kind)
                    if clip.source not in media:
                        media[clip.source] = {
                            "duration": duration,
                            "streams": [{k: v for k, v in stream.items() if k in {"index", "codec_type", "codec_name", "duration", "width", "height", "sample_rate"}} for stream in streams],
                        }
                    if not any(x.get("codec_type") == kind for x in streams):
                        issues.append(ValidationIssue("MISSING_STREAM", "error", f"source has no {kind} stream", **common))
                    if stream_duration is None:
                        issues.append(ValidationIssue("MEDIA_DURATION_UNKNOWN", "error", "source duration could not be determined", **common))
                    elif clip.in_point + clip.duration > stream_duration + 1e-3:
                        issues.append(ValidationIssue(
                            "CLIP_SOURCE_OUT_OF_BOUNDS", "error",
                            f"clip source end {clip.in_point + clip.duration:g}s exceeds {kind} stream duration {stream_duration:g}s",
                            **common,
                        ))

        final_intervals: list[tuple[float, float]] = []
        visible_clips: list[dict[str, Any]] = []
        track_coverage = []
        for track_index, track in enumerate(project.video_tracks):
            intervals = []
            if track.enabled:
                intervals = [(clip.start, clip.start + clip.duration) for clip in track.clips if clip.opacity > 0]
                final_intervals.extend(intervals)
                for clip_index, clip in enumerate(track.clips):
                    if clip.opacity > 0:
                        visible_clips.append({
                            "trackId": track.id, "trackKind": "video", "trackIndex": track_index, "clipIndex": clip_index,
                            "clipId": clip.id, "metadata": clip.metadata,
                            "timeRange": _range(clip.start, clip.start + clip.duration),
                        })
            track_coverage.append({
                "trackId": track.id, "trackIndex": track_index, "enabled": track.enabled,
                "ranges": [_range(a, b) for a, b in _merge(intervals)],
            })
        intentional_hold_intervals = [(slot.start, slot.end) for slot in project.hold_slots]
        final_gaps = _gaps([*final_intervals, *intentional_hold_intervals], project.main_duration)
        for start, end in final_gaps:
            related = [x for x in visible_clips if abs(x["timeRange"]["end"] - start) < 1e-3 or abs(x["timeRange"]["start"] - end) < 1e-3]
            issues.append(ValidationIssue(
                "VIDEO_GAP", "error", "no enabled visible video clip covers this output range; rendered background may be pure black",
                time_range=_range(start, end), related_clips=related or None,
            ))
        coverage = {
            "releaseProjectContract": release_contract_coverage,
            "replacementBindings": replacement_coverage,
            "tracks": track_coverage,
            "finalVideoRanges": [_range(a, b) for a, b in _merge(final_intervals)],
            "finalVideoGaps": [_range(a, b) for a, b in final_gaps],
            "subtitles": subtitle_coverage,
            "narrative": narrative_coverage,
            "cutReason": cut_reason_coverage,
            "outro": outro_coverage,
            "cleanup": cleanup_coverage,
            "audioSafety": audio_coverage,
            "sourceAdmission": source_coverage,
            "releaseGate": release_coverage,
            "holdSlots": hold_coverage,
            "shotRecipes": recipe_coverage,
        }
        return ValidationReport(
            not any(x.severity == "error" for x in issues), project.duration,
            len(project.video_tracks), len(project.audio_tracks), len(project.subtitle_tracks), tuple(issues), media, coverage,
        )
