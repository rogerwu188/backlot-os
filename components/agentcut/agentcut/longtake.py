from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import AgentCutError, ValidationError


CAPABILITY_ID = "CL2X-352"
CAPABILITY_VERSION = "1.0"


def _load_object(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return json.loads(json.dumps(source))
    path = Path(source).resolve()
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValidationError("long-take request must be a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def longtake_preflight(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    request = _load_object(source)
    if request.get("version", "1.0") != "1.0":
        raise ValidationError("long-take request version must be '1.0'")
    continuous = request.get("continuousCameraRequired", True)
    paid = request.get("paidSubmission", True)
    for name, value in (("continuousCameraRequired", continuous), ("paidSubmission", paid)):
        if not isinstance(value, bool):
            raise ValidationError(f"{name} must be a boolean")
    input_spec = request.get("input") or {}
    provider = request.get("provider") or {}
    if not isinstance(input_spec, dict) or not isinstance(provider, dict):
        raise ValidationError("input and provider must be objects")
    mode = input_spec.get("mode", "single-anchor")
    if mode not in {"single-anchor", "multi-image"}:
        raise ValidationError("input.mode must be single-anchor or multi-image")
    anchors = input_spec.get("anchors") or []
    if not isinstance(anchors, list) or not anchors:
        raise ValidationError("input.anchors must be a non-empty array")
    anchor_manifest = []
    previous = -1.0
    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, dict):
            raise ValidationError(f"input.anchors[{index}] must be an object")
        anchor_id = anchor.get("id")
        time_value = anchor.get("time")
        if not isinstance(anchor_id, str) or not anchor_id:
            raise ValidationError(f"input.anchors[{index}].id must be a non-empty string")
        if isinstance(time_value, bool) or not isinstance(time_value, (int, float)) or time_value < 0:
            raise ValidationError(f"input.anchors[{index}].time must be a non-negative number")
        time_value = float(time_value)
        if time_value <= previous:
            raise ValidationError("input anchor times must be strictly increasing")
        previous = time_value
        anchor_manifest.append({"id": anchor_id, "time": time_value})
    cue_blocks = input_spec.get("cueBlocks") or []
    if not isinstance(cue_blocks, list):
        raise ValidationError("input.cueBlocks must be an array")
    multi_anchor = mode == "multi-image" or len(anchors) > 1
    guarantee = provider.get("guaranteesInterAnchorInterpolation")
    if guarantee is not None and not isinstance(guarantee, bool):
        raise ValidationError("provider.guaranteesInterAnchorInterpolation must be a boolean")
    issues = []
    if continuous and multi_anchor and guarantee is not True:
        issues.append({
            "code": "LONG_TAKE_INTERPOLATION_GUARANTEE_REQUIRED",
            "severity": "error",
            "message": "multi-image continuous-camera submission requires a provider guarantee of interpolation without inter-anchor hard cuts",
            "anchorTimes": [item["time"] for item in anchor_manifest],
        })
    if continuous and multi_anchor and len(cue_blocks) > 1 and guarantee is not True:
        issues.append({
            "code": "LONG_TAKE_TEMPORAL_COMPOSITION_RISK",
            "severity": "error",
            "message": "multiple image anchors plus segmented cue blocks may be interpreted as temporal composition cuts",
            "cueBlockCount": len(cue_blocks),
        })
    allowed = not any(item["severity"] == "error" for item in issues)
    decision = "ALLOW_SUBMISSION" if allowed else ("FAIL_BEFORE_PAID_SUBMISSION" if paid else "REJECT_REQUEST")
    return {
        "capability": CAPABILITY_ID, "capabilityVersion": CAPABILITY_VERSION,
        "allowed": allowed, "decision": decision, "paidSubmission": paid,
        "continuousCameraRequired": continuous, "inputMode": mode,
        "anchorCount": len(anchors), "anchors": anchor_manifest,
        "provider": {"name": provider.get("name"), "guaranteesInterAnchorInterpolation": guarantee is True},
        "issues": issues,
    }


@dataclass(frozen=True)
class LongTakeValidator:
    ffmpeg: str
    ffprobe: str

    def validate(self, video: str | Path, *, anchor_times: list[float] | None = None,
                 scene_threshold: float = 0.20, anchor_window: float = 0.75,
                 continuous_camera_required: bool = True) -> dict[str, Any]:
        path = Path(video).resolve()
        if not path.is_file() or path.stat().st_size == 0:
            raise ValidationError(f"long-take video is missing or empty: {path}")
        if not 0 < scene_threshold < 1:
            raise ValidationError("sceneThreshold must be between 0 and 1")
        if anchor_window < 0:
            raise ValidationError("anchorWindow must be non-negative")
        anchors = sorted(float(value) for value in (anchor_times or []))
        if any(value < 0 for value in anchors):
            raise ValidationError("anchorTimes must be non-negative")
        if shutil.which(self.ffmpeg) is None or shutil.which(self.ffprobe) is None:
            raise AgentCutError("FFmpeg and FFprobe are required for long-take validation")
        probe = subprocess.run([
            self.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path),
        ], capture_output=True, text=True)
        if probe.returncode != 0:
            raise AgentCutError(probe.stderr.strip() or "FFprobe failed")
        try:
            duration = float(json.loads(probe.stdout)["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AgentCutError("could not determine long-take duration") from exc
        detection = subprocess.run([
            self.ffmpeg, "-hide_banner", "-loglevel", "info", "-i", str(path),
            "-vf", f"select='gt(scene,{scene_threshold:g})',showinfo", "-an", "-f", "null", "-",
        ], capture_output=True, text=True)
        if detection.returncode != 0:
            raise AgentCutError(detection.stderr.strip() or "hard-cut detection failed")
        times = sorted({round(float(value), 6) for value in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", detection.stderr)})
        cuts = []
        for timestamp in times:
            nearest = min(anchors, key=lambda value: abs(value - timestamp)) if anchors else None
            delta = abs(nearest - timestamp) if nearest is not None else None
            cuts.append({
                "time": timestamp,
                "nearestAnchor": nearest,
                "anchorDelta": round(delta, 6) if delta is not None else None,
                "interAnchorHardCut": bool(delta is not None and delta <= anchor_window),
            })
        issues = []
        if continuous_camera_required and cuts:
            issues.append({
                "code": "LONG_TAKE_HARD_CUT_DETECTED", "severity": "error",
                "message": f"continuous-camera candidate contains {len(cuts)} detected hard cut(s)",
                "timestamps": times,
            })
        anchor_cuts = [item for item in cuts if item["interAnchorHardCut"]]
        if anchor_cuts:
            issues.append({
                "code": "LONG_TAKE_INTER_ANCHOR_HARD_CUT", "severity": "error",
                "message": "hard cuts cluster around temporal image-anchor boundaries",
                "cuts": anchor_cuts,
            })
        valid = not any(item["severity"] == "error" for item in issues)
        return {
            "capability": CAPABILITY_ID, "capabilityVersion": CAPABILITY_VERSION,
            "valid": valid, "decision": "ACCEPT" if valid else "REJECT",
            "video": str(path), "sha256": _sha256(path), "duration": duration,
            "continuousCameraRequired": continuous_camera_required,
            "sceneThreshold": scene_threshold, "anchorWindow": anchor_window,
            "anchorTimes": anchors, "hardCuts": cuts, "issues": issues,
        }
