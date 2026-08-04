#!/usr/bin/env python3
"""Reject BGM claims that lack real sources, a real mix track, or audible energy."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from media_binary import resolve_media_binary
except ModuleNotFoundError:  # Imported as tools.bgm_authenticity_gate.
    from tools.media_binary import resolve_media_binary


ROOT = Path(__file__).resolve().parents[1]
SOURCE_TYPES = {"GENERATED_EPISODE_BGM", "LIBRARY_FALLBACK"}
MAX_BGM_COVERAGE_RATIO = 0.85
MIN_AMBIENCE_ONLY_SECONDS = 8.0
MAX_DIALOGUE_SPEECH_BAND_MEAN_INCREASE_DB = 1.0
MAX_DIALOGUE_SPEECH_BAND_PEAK_INCREASE_DB = 1.5
MIN_DIALOGUE_TO_BGM_SPEECH_BAND_MARGIN_DB = 12.0
MAX_TOUCHING_CUE_BOUNDARY_STEP_DB = 6.0
MIN_SELECTIVE_STEM_GLOBAL_MEAN_DB = -40.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def volume(path: Path) -> dict:
    ffmpeg = resolve_media_binary("ffmpeg")
    completed = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        text=True,
        capture_output=True,
    )
    text = completed.stderr
    mean = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", text)
    maximum = re.search(r"max_volume:\s*(-?[0-9.]+) dB", text)
    return {
        "mean_volume_db": float(mean.group(1)) if mean else None,
        "max_volume_db": float(maximum.group(1)) if maximum else None,
    }


def band_volume(path: Path, start: float, duration: float) -> dict:
    """Measure the dialogue-intelligibility band for one normal-speed cue window."""
    ffmpeg = resolve_media_binary("ffmpeg")
    completed = subprocess.run(
        [
            str(ffmpeg), "-hide_banner", "-nostats", "-ss", str(start), "-t", str(duration),
            "-i", str(path), "-vn", "-af", "highpass=f=300,lowpass=f=3400,volumedetect",
            "-f", "null", "-",
        ],
        text=True,
        capture_output=True,
    )
    text = completed.stderr
    mean = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", text)
    maximum = re.search(r"max_volume:\s*(-?[0-9.]+) dB", text)
    return {
        "mean_volume_db": float(mean.group(1)) if mean else None,
        "max_volume_db": float(maximum.group(1)) if maximum else None,
    }


def validate_mix_metrics(dialogue_metrics: list[dict], boundary_metrics: list[dict]) -> list[str]:
    """Fail closed on measured speech masking or abrupt touching-cue handoffs."""
    failures: list[str] = []
    for row in dialogue_metrics:
        cue_id = row.get("cue_id")
        mean_increase = row.get("mean_increase_db")
        peak_increase = row.get("peak_increase_db")
        margin = row.get("dialogue_to_bgm_mean_margin_db")
        if mean_increase is None or mean_increase > MAX_DIALOGUE_SPEECH_BAND_MEAN_INCREASE_DB:
            failures.append(f"BGM_DIALOGUE_SPEECH_BAND_MEAN_MASKING:{cue_id}")
        if peak_increase is None or peak_increase > MAX_DIALOGUE_SPEECH_BAND_PEAK_INCREASE_DB:
            failures.append(f"BGM_DIALOGUE_SPEECH_BAND_PEAK_MASKING:{cue_id}")
        if margin is None or margin < MIN_DIALOGUE_TO_BGM_SPEECH_BAND_MARGIN_DB:
            failures.append(f"BGM_DIALOGUE_TO_MUSIC_MARGIN_LT_12_DB:{cue_id}")
    for row in boundary_metrics:
        step = row.get("boundary_step_db")
        if step is None or abs(step) > MAX_TOUCHING_CUE_BOUNDARY_STEP_DB:
            failures.append(f"BGM_TOUCHING_CUE_BOUNDARY_STEP_GT_6_DB:{row.get('boundary_seconds')}")
    return failures


def measure_mix_metrics(project: dict, baseline: Path, final: Path, stem: Path) -> tuple[list[dict], list[dict]]:
    tracks = project.get("timeline", {}).get("audioTracks", [])
    bgm_track = next((track for track in tracks if track.get("id") == "Audio.BGM"), {})
    clips = list(bgm_track.get("clips") or [])
    dialogue_metrics: list[dict] = []
    for clip in clips:
        if (clip.get("metadata") or {}).get("dialogue_present") is not True:
            continue
        start = float(clip.get("start", 0))
        duration = float(clip.get("duration", 0))
        base = band_volume(baseline, start, duration)
        mixed = band_volume(final, start, duration)
        music = band_volume(stem, start, duration)
        base_mean = base.get("mean_volume_db")
        mixed_mean = mixed.get("mean_volume_db")
        base_peak = base.get("max_volume_db")
        mixed_peak = mixed.get("max_volume_db")
        music_mean = music.get("mean_volume_db")
        dialogue_metrics.append({
            "cue_id": clip.get("id"),
            "start": start,
            "duration": duration,
            "baseline": base,
            "mixed": mixed,
            "bgm_stem": music,
            "mean_increase_db": round(mixed_mean - base_mean, 3) if None not in (mixed_mean, base_mean) else None,
            "peak_increase_db": round(mixed_peak - base_peak, 3) if None not in (mixed_peak, base_peak) else None,
            "dialogue_to_bgm_mean_margin_db": round(base_mean - music_mean, 3) if None not in (music_mean, base_mean) else None,
        })
    boundary_metrics: list[dict] = []
    ordered = sorted(clips, key=lambda row: float(row.get("start", 0)))
    for left, right in zip(ordered, ordered[1:]):
        boundary = float(right.get("start", 0))
        left_end = float(left.get("start", 0)) + float(left.get("duration", 0))
        if abs(left_end - boundary) > 0.001:
            continue
        before = band_volume(stem, max(0.0, boundary - 0.5), 0.5)
        after = band_volume(stem, boundary, 0.5)
        before_mean = before.get("mean_volume_db")
        after_mean = after.get("mean_volume_db")
        boundary_metrics.append({
            "boundary_seconds": boundary,
            "left_cue_id": left.get("id"),
            "right_cue_id": right.get("id"),
            "before": before,
            "after": after,
            "boundary_step_db": round(after_mean - before_mean, 3) if None not in (after_mean, before_mean) else None,
        })
    return dialogue_metrics, boundary_metrics


def validate_bgm_contract(project: dict) -> list[str]:
    failures: list[str] = []
    contract = (project.get("metadata") or {}).get("bgm_contract") or {}
    source_type = str(contract.get("source_type") or "")
    if source_type not in SOURCE_TYPES:
        return ["BGM_SOURCE_PRIORITY_CONTRACT_MISSING"]
    duck = contract.get("dialogue_duck_db")
    if not isinstance(duck, (int, float)) or isinstance(duck, bool) or not -10.0 <= float(duck) <= -6.0:
        failures.append("BGM_DIALOGUE_DUCK_MUST_BE_MINUS_10_TO_MINUS_6_DB")
    if source_type == "GENERATED_EPISODE_BGM":
        if not str(contract.get("generation_task_id") or "").strip():
            failures.append("GENERATED_BGM_TASK_ID_MISSING")
        if not str(contract.get("generation_receipt") or "").strip():
            failures.append("GENERATED_BGM_RECEIPT_MISSING")
        if not str(contract.get("source_sha256") or "").strip():
            failures.append("GENERATED_BGM_SOURCE_SHA_MISSING")
        if not str(contract.get("credit_evidence") or "").strip():
            failures.append("GENERATED_BGM_CREDIT_EVIDENCE_MISSING")
    else:
        if not str(contract.get("music_id") or "").strip():
            failures.append("LIBRARY_BGM_MUSIC_ID_MISSING")
        if len(str(contract.get("fallback_reason") or "").strip()) < 12:
            failures.append("LIBRARY_BGM_FALLBACK_REASON_MISSING")
        similarity = contract.get("cross_episode_similarity") or {}
        if similarity.get("status") != "PASS" or not str(similarity.get("report") or "").strip():
            failures.append("LIBRARY_BGM_CROSS_EPISODE_SIMILARITY_NOT_PASS")
    return failures


def _merged_duration(intervals: list[tuple[float, float]]) -> float:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start for start, end in merged)


def validate_bgm_cue_policy(project: dict, bgm_track: dict | None = None) -> list[str]:
    """Reject missing cue intent, wall-to-wall beds, and dialogue masking."""
    failures: list[str] = []
    policy = (project.get("metadata") or {}).get("bgm_cue_policy") or {}
    if policy.get("mode") != "SELECTIVE_NARRATIVE_CUES":
        failures.append("BGM_SELECTIVE_CUE_POLICY_MISSING")
    if policy.get("ambience_only_required") is not True:
        failures.append("BGM_AMBIENCE_ONLY_WINDOW_NOT_REQUIRED")

    tracks = project.get("timeline", {}).get("audioTracks", [])
    bgm_track = bgm_track or next((track for track in tracks if track.get("id") == "Audio.BGM"), None)
    clips = list((bgm_track or {}).get("clips") or [])
    if not clips:
        return failures

    video_clips = [
        clip
        for track in project.get("timeline", {}).get("videoTracks", [])
        for clip in track.get("clips", [])
    ]
    episode_end = max(
        (float(clip.get("start", 0)) + float(clip.get("duration", 0)) for clip in video_clips),
        default=0.0,
    )
    intervals = [
        (float(clip.get("start", 0)), float(clip.get("start", 0)) + float(clip.get("duration", 0)))
        for clip in clips
    ]
    covered = _merged_duration(intervals)
    if episode_end <= 0:
        failures.append("BGM_EPISODE_DURATION_UNAVAILABLE")
    else:
        if covered / episode_end > MAX_BGM_COVERAGE_RATIO:
            failures.append("BGM_WALL_TO_WALL_COVERAGE_GT_85_PERCENT")
        if episode_end - covered < MIN_AMBIENCE_ONLY_SECONDS:
            failures.append("BGM_AMBIENCE_ONLY_WINDOW_LT_8_SECONDS")

    allowed_roles = {"OPENING_MYSTERY", "INVESTIGATION_TRANSITION", "ACTION_ESCALATION", "ENDING_HOOK"}
    for clip in clips:
        clip_metadata = clip.get("metadata") or {}
        if str(clip_metadata.get("cue_role") or "") not in allowed_roles:
            failures.append(f"BGM_CUE_ROLE_MISSING:{clip.get('id')}")
        volume_value = clip.get("volume")
        volume = float(volume_value) if isinstance(volume_value, (int, float)) else 99.0
        if clip_metadata.get("dialogue_present") is True and volume > 0.16:
            failures.append(f"BGM_DIALOGUE_CUE_VOLUME_GT_0P16:{clip.get('id')}")
        if clip_metadata.get("dialogue_present") is not True and volume > 0.32:
            failures.append(f"BGM_NON_DIALOGUE_CUE_VOLUME_GT_0P32:{clip.get('id')}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--stem", required=True)
    parser.add_argument("--final", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--generation-log")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    project_path = Path(args.project).resolve()
    stem_path = Path(args.stem).resolve()
    final_path = Path(args.final).resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    contract = (project.get("metadata") or {}).get("bgm_contract") or {}
    bgm_track = next(
        (track for track in project.get("timeline", {}).get("audioTracks", []) if track.get("id") == "Audio.BGM"),
        None,
    )
    failures = []
    failures.extend(validate_bgm_contract(project))
    failures.extend(validate_bgm_cue_policy(project, bgm_track))
    sources = []
    clips = list((bgm_track or {}).get("clips") or [])
    if not clips:
        failures.append("AUDIO_BGM_TRACK_OR_CLIPS_MISSING")
    for clip in clips:
        source = Path(str(clip.get("source") or ""))
        if not source.is_file() or source.stat().st_size == 0:
            failures.append(f"BGM_SOURCE_MISSING:{clip.get('id')}")
            continue
        sources.append({
            "clip_id": clip.get("id"),
            "path": str(source),
            "sha256": sha256(source),
            "size_bytes": source.stat().st_size,
            "volume": clip.get("volume"),
            "duration": clip.get("duration"),
        })
    if not stem_path.is_file() or stem_path.stat().st_size == 0:
        failures.append("BGM_SOLO_STEM_MISSING")
        stem_metrics = {}
    else:
        stem_metrics = volume(stem_path)
        if stem_metrics["mean_volume_db"] is None or stem_metrics["mean_volume_db"] < MIN_SELECTIVE_STEM_GLOBAL_MEAN_DB:
            failures.append("BGM_STEM_NOT_AUDIBLE_MEAN_BELOW_MINUS_40_DB")
        if stem_metrics["max_volume_db"] is None or stem_metrics["max_volume_db"] < -18:
            failures.append("BGM_STEM_NOT_AUDIBLE_PEAK_BELOW_MINUS_18_DB")
    if not final_path.is_file() or final_path.stat().st_size == 0:
        failures.append("MIXED_VIDEO_MISSING")

    baseline_path = Path(args.baseline).resolve() if args.baseline else None
    spectral_required = ((project.get("metadata") or {}).get("bgm_cue_policy") or {}).get(
        "spectral_masking_gate_required"
    ) is True
    dialogue_metrics: list[dict] = []
    boundary_metrics: list[dict] = []
    if spectral_required and (baseline_path is None or not baseline_path.is_file()):
        failures.append("BGM_NO_BGM_BASELINE_REQUIRED_FOR_SPECTRAL_GATE")
    elif baseline_path and baseline_path.is_file() and final_path.is_file() and stem_path.is_file():
        dialogue_metrics, boundary_metrics = measure_mix_metrics(project, baseline_path, final_path, stem_path)
        failures.extend(validate_mix_metrics(dialogue_metrics, boundary_metrics))

    generation_log = Path(args.generation_log).resolve() if args.generation_log else None
    generation_text = generation_log.read_text(encoding="utf-8") if generation_log and generation_log.is_file() else ""
    generation_receipt = None
    generation_credit = None
    generation_status = "FAILED_HTTP_403_ZERO_CREDIT" if "403: Forbidden" in generation_text else "NOT_APPLICABLE_LIBRARY_SOURCE"
    generation_task_id = None
    generation_credit_value = None
    if contract.get("source_type") == "GENERATED_EPISODE_BGM":
        receipt_value = str(contract.get("generation_receipt") or "")
        credit_value = str(contract.get("credit_evidence") or "")
        generation_receipt = (ROOT / receipt_value).resolve() if receipt_value and not Path(receipt_value).is_absolute() else Path(receipt_value).resolve()
        generation_credit = (ROOT / credit_value).resolve() if credit_value and not Path(credit_value).is_absolute() else Path(credit_value).resolve()
        if not generation_receipt.is_file():
            failures.append("GENERATED_BGM_RECEIPT_FILE_MISSING")
        if not generation_credit.is_file():
            failures.append("GENERATED_BGM_CREDIT_EVIDENCE_FILE_MISSING")
        if generation_receipt.is_file():
            receipt_payload = json.loads(generation_receipt.read_text(encoding="utf-8"))
            generation_task_id = receipt_payload.get("task_id")
            if generation_task_id != contract.get("generation_task_id"):
                failures.append("GENERATED_BGM_TASK_ID_RECEIPT_MISMATCH")
            receipt_shas = {row.get("sha256") for row in receipt_payload.get("files", [])}
            if contract.get("source_sha256") not in receipt_shas:
                failures.append("GENERATED_BGM_SOURCE_SHA_RECEIPT_MISMATCH")
            generation_credit_value = (receipt_payload.get("credit") or {}).get("net_charged_credits")
        if generation_credit.is_file():
            credit_payload = json.loads(generation_credit.read_text(encoding="utf-8"))
            if credit_payload.get("status") != "PASS_EXACT_ISOLATED_LEDGER_NET":
                failures.append("GENERATED_BGM_EXACT_CREDIT_LEDGER_NOT_PASS")
            if generation_credit_value is not None and credit_payload.get("net_charged_credits") != generation_credit_value:
                failures.append("GENERATED_BGM_CREDIT_RECEIPT_MISMATCH")
        generation_status = "VERIFIED_ACCOUNT_GENERATED" if not any(value.startswith("GENERATED_BGM_") for value in failures) else "FAILED_PROVENANCE_VERIFICATION"
    report = {
        "schema": "qingshan.bgm_authenticity_gate.v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_LOCAL_SOURCE_AND_MIX" if not failures else "FAIL",
        "release_eligible": not failures,
        "project": str(project_path),
        "project_sha256": sha256(project_path),
        "bgm_clip_count": len(clips),
        "bgm_sources": sources,
        "solo_stem": {
            "path": str(stem_path),
            "sha256": sha256(stem_path) if stem_path.is_file() else None,
            **stem_metrics,
        },
        "mixed_video": {
            "path": str(final_path),
            "sha256": sha256(final_path) if final_path.is_file() else None,
        },
        "spectral_masking_gate": {
            "required": spectral_required,
            "baseline": str(baseline_path) if baseline_path else None,
            "baseline_sha256": sha256(baseline_path) if baseline_path and baseline_path.is_file() else None,
            "dialogue_cues": dialogue_metrics,
            "touching_cue_boundaries": boundary_metrics,
        },
        "new_agentcut_bgm_generation": {
            "status": generation_status,
            "task_id": generation_task_id,
            "credit": generation_credit_value,
            "generation_receipt": str(generation_receipt) if generation_receipt else None,
            "credit_evidence": str(generation_credit) if generation_credit else None,
            "log": str(generation_log) if generation_log else None,
            "hard_blocker": "Giggle AgentCut BGM endpoint returned HTTP 403 before a task ID was issued." if generation_status == "FAILED_HTTP_403_ZERO_CREDIT" else None,
        },
        "failures": failures,
        "policy": "New episode BGM is primary. Generated BGM requires task, receipt, source SHA and exact credit provenance. A library fallback requires a recorded reason and cross-episode similarity PASS. Every path requires -6 to -10 dB dialogue ducking, real local sources, Audio.BGM, an audible solo stem, and a mixed output.",
    }
    output = Path(args.out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "generation_status": generation_status, "failures": failures}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
