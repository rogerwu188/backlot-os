from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import AgentCutError, ValidationError
from .models import Project


@dataclass(frozen=True)
class FinalVisualPolicy:
    """Post-render visual stagnation policy.

    The defaults intentionally sample slowly and ignore the subtitle band.  This
    is a release gate, not a frame-perfect cadence replacement: perceptual hashes
    establish composition similarity while pixel motion prevents hash-only false
    positives.
    """

    enabled: bool = False
    required: bool = False
    sample_fps: float = 2.0
    crop_bottom_ratio: float = 0.22
    freeze_phash_distance_max: int = 4
    freeze_ahash_distance_max: int = 4
    freeze_motion_mean_max: float = 0.018
    max_near_freeze_seconds: float = 4.0
    freeze_gap_tolerance_seconds: float = 1.5
    min_freeze_pair_ratio: float = 0.65
    composition_phash_distance_max: int = 8
    composition_ahash_distance_max: int = 10
    composition_gap_seconds: float = 2.5
    min_composition_occurrence_seconds: float = 1.0
    max_composition_occurrences: int = 2
    max_composition_ratio: float = 0.06
    min_timeline_seconds_for_composition_ratio: float = 30.0
    report_path: str | None = None
    allowed_intervals: tuple[dict[str, Any], ...] = ()

    @classmethod
    def parse(cls, value: Any, *, base_dir: Path | None = None) -> "FinalVisualPolicy":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValidationError("finalVisualPolicy must be an object")

        def boolean(name: str, default: bool) -> bool:
            item = value.get(name, default)
            if not isinstance(item, bool):
                raise ValidationError(f"finalVisualPolicy.{name} must be a boolean")
            return item

        def number(name: str, default: float, minimum: float, maximum: float | None = None) -> float:
            item = value.get(name, default)
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise ValidationError(f"finalVisualPolicy.{name} must be a number")
            item = float(item)
            if item < minimum or (maximum is not None and item > maximum):
                suffix = f" and <= {maximum:g}" if maximum is not None else ""
                raise ValidationError(f"finalVisualPolicy.{name} must be >= {minimum:g}{suffix}")
            return item

        def integer(name: str, default: int, minimum: int, maximum: int | None = None) -> int:
            item = value.get(name, default)
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValidationError(f"finalVisualPolicy.{name} must be an integer")
            if item < minimum or (maximum is not None and item > maximum):
                suffix = f" and <= {maximum}" if maximum is not None else ""
                raise ValidationError(f"finalVisualPolicy.{name} must be >= {minimum}{suffix}")
            return item

        intervals = value.get("allowedIntervals", [])
        if not isinstance(intervals, list):
            raise ValidationError("finalVisualPolicy.allowedIntervals must be an array")
        normalized_intervals = []
        for index, item in enumerate(intervals):
            path = f"finalVisualPolicy.allowedIntervals[{index}]"
            if not isinstance(item, dict):
                raise ValidationError(f"{path} must be an object")
            start = item.get("start")
            end = item.get("end")
            reason = item.get("reason")
            if (isinstance(start, bool) or not isinstance(start, (int, float)) or start < 0 or
                    isinstance(end, bool) or not isinstance(end, (int, float)) or end <= start):
                raise ValidationError(f"{path} requires numeric 0 <= start < end")
            if not isinstance(reason, str) or not reason.strip():
                raise ValidationError(f"{path}.reason must be a non-empty rollback-auditable reason")
            normalized_intervals.append({"start": float(start), "end": float(end), "reason": reason.strip()})

        report_path = value.get("reportPath")
        if report_path is not None and (not isinstance(report_path, str) or not report_path.strip()):
            raise ValidationError("finalVisualPolicy.reportPath must be a non-empty string")
        if report_path and base_dir and not Path(report_path).is_absolute():
            report_path = str((base_dir / report_path).resolve())

        return cls(
            enabled=boolean("enabled", False), required=boolean("required", False),
            sample_fps=number("sampleFps", 2.0, 0.25, 10.0),
            crop_bottom_ratio=number("cropBottomRatio", 0.22, 0.0, 0.45),
            freeze_phash_distance_max=integer("freezePHashDistanceMax", 4, 0, 64),
            freeze_ahash_distance_max=integer("freezeAHashDistanceMax", 4, 0, 64),
            freeze_motion_mean_max=number("freezeMotionMeanMax", 0.018, 0.0, 1.0),
            max_near_freeze_seconds=number("maxNearFreezeSeconds", 4.0, 0.5),
            freeze_gap_tolerance_seconds=number("freezeGapToleranceSeconds", 1.5, 0.0, 5.0),
            min_freeze_pair_ratio=number("minFreezePairRatio", 0.65, 0.0, 1.0),
            composition_phash_distance_max=integer("compositionPHashDistanceMax", 8, 0, 64),
            composition_ahash_distance_max=integer("compositionAHashDistanceMax", 10, 0, 64),
            composition_gap_seconds=number("compositionGapSeconds", 2.5, 0.0),
            min_composition_occurrence_seconds=number("minCompositionOccurrenceSeconds", 1.0, 0.25),
            max_composition_occurrences=integer("maxCompositionOccurrences", 2, 1),
            max_composition_ratio=number("maxCompositionRatio", 0.06, 0.0, 1.0),
            min_timeline_seconds_for_composition_ratio=number(
                "minTimelineSecondsForCompositionRatio", 30.0, 1.0,
            ),
            report_path=report_path, allowed_intervals=tuple(normalized_intervals),
        )

    def public_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        return {
            "enabled": raw["enabled"], "required": raw["required"], "sampleFps": raw["sample_fps"],
            "cropBottomRatio": raw["crop_bottom_ratio"],
            "freezePHashDistanceMax": raw["freeze_phash_distance_max"],
            "freezeAHashDistanceMax": raw["freeze_ahash_distance_max"],
            "freezeMotionMeanMax": raw["freeze_motion_mean_max"],
            "maxNearFreezeSeconds": raw["max_near_freeze_seconds"],
            "freezeGapToleranceSeconds": raw["freeze_gap_tolerance_seconds"],
            "minFreezePairRatio": raw["min_freeze_pair_ratio"],
            "compositionPHashDistanceMax": raw["composition_phash_distance_max"],
            "compositionAHashDistanceMax": raw["composition_ahash_distance_max"],
            "compositionGapSeconds": raw["composition_gap_seconds"],
            "minCompositionOccurrenceSeconds": raw["min_composition_occurrence_seconds"],
            "maxCompositionOccurrences": raw["max_composition_occurrences"],
            "maxCompositionRatio": raw["max_composition_ratio"],
            "minTimelineSecondsForCompositionRatio": raw["min_timeline_seconds_for_composition_ratio"],
            "allowedIntervals": list(raw["allowed_intervals"]),
        }


@dataclass(frozen=True)
class _FrameEvidence:
    index: int
    time: float
    phash: int
    ahash: int
    pixels: bytes


def _hamming(left: int, right: int) -> int:
    value = left ^ right
    return value.bit_count() if hasattr(value, "bit_count") else bin(value).count("1")


def _ahash(pixels: bytes) -> int:
    # Average 4x4 cells into an 8x8 luminance map.
    cells = []
    for cell_y in range(8):
        for cell_x in range(8):
            total = 0
            for y in range(cell_y * 4, cell_y * 4 + 4):
                offset = y * 32 + cell_x * 4
                total += sum(pixels[offset:offset + 4])
            cells.append(total / 16.0)
    mean = sum(cells) / len(cells)
    result = 0
    for value in cells:
        result = (result << 1) | int(value >= mean)
    return result


_COS = tuple(tuple(math.cos((2 * x + 1) * u * math.pi / 64) for x in range(32)) for u in range(8))


def _phash(pixels: bytes) -> int:
    # Low-frequency 8x8 DCT over the 32x32 release sample.
    row_dct = [[sum(pixels[y * 32 + x] * _COS[u][x] for x in range(32)) for u in range(8)] for y in range(32)]
    coefficients = [sum(row_dct[y][u] * _COS[v][y] for y in range(32)) for v in range(8) for u in range(8)]
    median = statistics.median(coefficients[1:])
    result = 0
    for value in coefficients:
        result = (result << 1) | int(value >= median)
    return result


def _motion(left: bytes, right: bytes) -> float:
    return sum(abs(a - b) for a, b in zip(left, right)) / (len(left) * 255.0)


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _round(value: float) -> float:
    return round(float(value), 6)


class FinalVisualValidator:
    def __init__(self, ffmpeg: str, ffprobe: str) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def _probe_duration(self, video: str | Path) -> float:
        process = subprocess.run([
            self.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=duration", "-of", "json", str(video),
        ], capture_output=True, text=True)
        try:
            duration = float(json.loads(process.stdout)["streams"][0]["duration"])
        except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise AgentCutError(f"unable to probe final video duration: {video}") from exc
        if not math.isfinite(duration) or duration <= 0:
            raise AgentCutError(f"invalid final video duration: {duration!r}")
        return duration

    def _sample(self, video: str | Path, policy: FinalVisualPolicy) -> list[_FrameEvidence]:
        retained = 1.0 - policy.crop_bottom_ratio
        crop = f"crop=iw:floor(ih*{retained:.9f}/2)*2:0:0"
        process = subprocess.run([
            self.ffmpeg, "-v", "error", "-i", str(video), "-an", "-vf",
            f"fps={policy.sample_fps:g},{crop},scale=32:32:flags=area,format=gray",
            "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
        ], capture_output=True)
        if process.returncode != 0:
            raise AgentCutError("final visual sampling failed: " + process.stderr.decode("utf-8", "replace")[-2000:])
        frame_bytes = 32 * 32
        if not process.stdout or len(process.stdout) % frame_bytes:
            raise AgentCutError("final visual sampling returned incomplete raw frames")
        return [
            _FrameEvidence(index, index / policy.sample_fps, _phash(pixels), _ahash(pixels), pixels)
            for index in range(len(process.stdout) // frame_bytes)
            for pixels in (process.stdout[index * frame_bytes:(index + 1) * frame_bytes],)
        ]

    @staticmethod
    def _project_intervals(project: Project | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        dialogue = []
        action = []
        if project is None:
            return dialogue, action
        for track in project.audio_tracks:
            track_is_dialogue = "dialogue" in track.id.lower() or "voice" in track.id.lower()
            if not track.enabled:
                continue
            for clip in track.clips:
                metadata = clip.metadata
                role = str(metadata.get("role", metadata.get("audio_role", ""))).lower()
                if track_is_dialogue or role in {"dialogue", "voice", "speech"} or metadata.get("dialogue_id"):
                    dialogue.append({"start": clip.start, "end": clip.start + clip.duration,
                                     "clipId": clip.id, "trackId": track.id})
        for track in project.video_tracks:
            if not track.enabled:
                continue
            for clip in track.clips:
                metadata = clip.metadata
                # action_required is an input promise, not proof that the rendered frames move.
                # Only an explicit motivated-hold/action declaration can exempt a freeze.
                declared = metadata.get("narrative_action_present") is True or metadata.get("motivated_hold") is True
                if declared:
                    action.append({"start": clip.start, "end": clip.start + clip.duration,
                                   "clipId": clip.id, "trackId": track.id,
                                   "reason": metadata.get("motivated_hold_reason") or "narrative_action_present"})
        return dialogue, action

    @staticmethod
    def _overlaps(start: float, end: float, intervals: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
        return [item for item in intervals if float(item["start"]) < end and float(item["end"]) > start]

    @staticmethod
    def _rollback_sources(project: Project | None, start: float, end: float) -> list[dict[str, Any]]:
        if project is None:
            return []
        result = []
        for track in project.video_tracks:
            if not track.enabled:
                continue
            for clip in track.clips:
                clip_end = clip.start + clip.duration
                if clip.start < end and clip_end > start:
                    result.append({
                        "clipId": clip.id, "trackId": track.id, "source": clip.source,
                        "timelineStart": _round(clip.start), "timelineEnd": _round(clip_end),
                        "suggestedRollback": "replace or shorten this clip, then re-render to a new immutable output",
                    })
        return result

    def analyze(self, video: str | Path, *, project: Project | None = None,
                policy: FinalVisualPolicy | None = None, reported_media_path: str | Path | None = None) -> dict[str, Any]:
        policy = policy or (project.final_visual_policy if project is not None else FinalVisualPolicy(enabled=True, required=True))
        path = Path(video).resolve()
        if not path.is_file():
            raise AgentCutError(f"final visual input not found: {path}")
        duration = self._probe_duration(path)
        frames = self._sample(path, policy)
        if len(frames) < 2:
            raise AgentCutError("final visual gate requires at least two sampled frames")
        dialogue_intervals, action_intervals = self._project_intervals(project)

        pair_evidence = []
        for left, right in zip(frames, frames[1:]):
            pair_evidence.append({
                "index": left.index, "start": left.time, "end": right.time,
                "pHashDistance": _hamming(left.phash, right.phash),
                "aHashDistance": _hamming(left.ahash, right.ahash),
                "motionMean": _motion(left.pixels, right.pixels),
            })

        frozen_runs: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for pair in pair_evidence:
            frozen = (pair["pHashDistance"] <= policy.freeze_phash_distance_max and
                      pair["aHashDistance"] <= policy.freeze_ahash_distance_max and
                      pair["motionMean"] <= policy.freeze_motion_mean_max)
            if frozen:
                current.append(pair)
            elif current:
                frozen_runs.append(current)
                current = []
        if current:
            frozen_runs.append(current)

        merged_runs: list[list[dict[str, Any]]] = []
        for run in frozen_runs:
            if (merged_runs and
                    float(run[0]["start"]) - float(merged_runs[-1][-1]["end"]) <= policy.freeze_gap_tolerance_seconds + 1e-9):
                merged_runs[-1].extend(run)
            else:
                merged_runs.append(list(run))

        near_freeze = []
        violations = []
        for run in merged_runs:
            start, end = float(run[0]["start"]), float(run[-1]["end"])
            run_duration = end - start
            pair_ratio = len(run) / max(1.0, run_duration * policy.sample_fps)
            dialogue_hits = self._overlaps(start, end, dialogue_intervals)
            action_hits = self._overlaps(start, end, action_intervals)
            allowed_hits = self._overlaps(start, end, policy.allowed_intervals)
            failed = (run_duration > policy.max_near_freeze_seconds and pair_ratio >= policy.min_freeze_pair_ratio and not dialogue_hits and
                      not action_hits and not allowed_hits)
            evidence = {
                "start": _round(start), "end": _round(end), "duration": _round(run_duration),
                "samplePairs": len(run),
                "nearFreezePairRatio": _round(pair_ratio),
                "pHashDistance": {"mean": _round(statistics.fmean(item["pHashDistance"] for item in run)),
                                  "max": max(item["pHashDistance"] for item in run)},
                "aHashDistance": {"mean": _round(statistics.fmean(item["aHashDistance"] for item in run)),
                                  "max": max(item["aHashDistance"] for item in run)},
                "motionMean": {"mean": _round(statistics.fmean(item["motionMean"] for item in run)),
                               "max": _round(max(item["motionMean"] for item in run))},
                "dialogueEvidence": dialogue_hits, "narrativeActionEvidence": action_hits,
                "allowedIntervalEvidence": allowed_hits, "decision": "FAIL" if failed else "OBSERVED",
            }
            near_freeze.append(evidence)
            if failed:
                violations.append({
                    "code": "FINAL_NEAR_FREEZE_EXCEEDED", "message": "unmotivated near-freeze exceeds release limit",
                    "timeCluster": {"start": evidence["start"], "end": evidence["end"], "duration": evidence["duration"]},
                    "evidence": {"pHashDistance": evidence["pHashDistance"], "aHashDistance": evidence["aHashDistance"],
                                 "motionMean": evidence["motionMean"]},
                    "threshold": {"maxNearFreezeSeconds": policy.max_near_freeze_seconds,
                                  "minFreezePairRatio": policy.min_freeze_pair_ratio,
                                  "freezeGapToleranceSeconds": policy.freeze_gap_tolerance_seconds,
                                  "requiresNoDialogue": True, "requiresNoNarrativeAction": True},
                    "rollbackSuggestions": self._rollback_sources(project, start, end),
                })

        # Greedy perceptual composition clusters.  A fixed representative avoids
        # transitive hash drift joining unrelated shots into one false cluster.
        clusters: list[dict[str, Any]] = []
        for frame in frames:
            best = None
            best_score = None
            for cluster in clusters:
                pd = _hamming(frame.phash, cluster["phash"])
                ad = _hamming(frame.ahash, cluster["ahash"])
                if pd <= policy.composition_phash_distance_max and ad <= policy.composition_ahash_distance_max:
                    score = pd + ad
                    if best_score is None or score < best_score:
                        best, best_score = cluster, score
            if best is None:
                clusters.append({"phash": frame.phash, "ahash": frame.ahash, "frames": [frame]})
            else:
                best["frames"].append(frame)

        composition_clusters = []
        total_samples = len(frames)
        max_gap_samples = max(1, int(round(policy.composition_gap_seconds * policy.sample_fps)))
        min_occurrence_samples = max(1, int(math.ceil(policy.min_composition_occurrence_seconds * policy.sample_fps)))
        for cluster_index, cluster in enumerate(clusters):
            members: list[_FrameEvidence] = cluster["frames"]
            windows: list[list[_FrameEvidence]] = []
            window: list[_FrameEvidence] = []
            for frame in members:
                if window and frame.index - window[-1].index > max_gap_samples:
                    windows.append(window)
                    window = []
                window.append(frame)
            if window:
                windows.append(window)
            qualifying = [item for item in windows if len(item) >= min_occurrence_samples]
            ratio = len(members) / total_samples
            if not qualifying and ratio < policy.max_composition_ratio:
                continue
            time_clusters = [
                {"start": _round(item[0].time), "end": _round(item[-1].time + 1 / policy.sample_fps),
                 "duration": _round((item[-1].index - item[0].index + 1) / policy.sample_fps),
                 "sampleCount": len(item)} for item in qualifying
            ]
            failed_occurrences = len(qualifying) > policy.max_composition_occurrences
            failed_ratio = duration >= policy.min_timeline_seconds_for_composition_ratio and ratio > policy.max_composition_ratio
            allowed_hits = [
                hit for time_cluster in time_clusters
                for hit in self._overlaps(time_cluster["start"], time_cluster["end"], policy.allowed_intervals)
            ]
            failed = (failed_occurrences or failed_ratio) and not allowed_hits
            item = {
                "clusterId": f"composition-{cluster_index:03d}", "sampleCount": len(members),
                "occurrenceCount": len(qualifying), "nearDuplicateRatio": _round(ratio),
                "timeClusters": time_clusters,
                "hashEvidence": {
                    "representativePHash": f"{cluster['phash']:016x}", "representativeAHash": f"{cluster['ahash']:016x}",
                    "pHashDistanceMax": policy.composition_phash_distance_max,
                    "aHashDistanceMax": policy.composition_ahash_distance_max,
                },
                "decision": "FAIL" if failed else "OBSERVED",
                "allowedIntervalEvidence": allowed_hits,
            }
            composition_clusters.append(item)
            if failed:
                cluster_start = min(member.time for member in members)
                cluster_end = max(member.time for member in members) + 1 / policy.sample_fps
                reasons = []
                if failed_occurrences:
                    reasons.append("occurrence_count_exceeded")
                if failed_ratio:
                    reasons.append("timeline_ratio_exceeded")
                violations.append({
                    "code": "FINAL_NEAR_DUPLICATE_COMPOSITION_EXCEEDED",
                    "message": "single composition repeats beyond the release budget", "reasons": reasons,
                    "timeClusters": time_clusters, "nearDuplicateRatio": item["nearDuplicateRatio"],
                    "occurrenceCount": len(qualifying),
                    "threshold": {"maxCompositionOccurrences": policy.max_composition_occurrences,
                                  "maxCompositionRatio": policy.max_composition_ratio,
                                  "minTimelineSecondsForCompositionRatio": policy.min_timeline_seconds_for_composition_ratio},
                    "hashEvidence": item["hashEvidence"],
                    "rollbackSuggestions": self._rollback_sources(project, cluster_start, cluster_end),
                })

        report_media = Path(reported_media_path).resolve() if reported_media_path else path
        hard_gate_passed = not violations
        return {
            "schema": "agentcut.final-visual-gate.v1", "status": "PASS" if hard_gate_passed else "FAIL",
            "hardGatePassed": hard_gate_passed, "media": {
                "path": str(report_media), "analyzedPath": str(path), "sha256": _sha256(path),
                "duration": _round(duration), "sampleCount": len(frames), "sampleFps": policy.sample_fps,
            },
            "policy": policy.public_dict(),
            "timelineEvidence": {"dialogueIntervals": dialogue_intervals, "narrativeActionIntervals": action_intervals},
            "nearFreeze": {"clusterCount": len(near_freeze), "clusters": near_freeze},
            "nearDuplicate": {"evaluatedClusterCount": len(clusters), "reportedClusterCount": len(composition_clusters),
                              "clusters": composition_clusters},
            "violations": violations,
            "rollback": {
                "sourceFilesModified": False, "outputReplacementAuthorized": False,
                "recommendation": "keep the current output immutable; recut/replace only cited clips and render a new candidate",
            },
            "platformMutationAuthorized": False,
        }

    @staticmethod
    def write_report(path: str | Path, report: dict[str, Any]) -> str:
        destination = Path(path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".{destination.name}.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, destination)
        return str(destination)
