from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .errors import AgentCutError


def _mean_volume(ffmpeg: str, source: str, pan: str) -> float:
    process = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", source, "-af", f"{pan},volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    match = re.search(r"mean_volume:\s*(-?inf|[-+0-9.]+) dB", process.stderr)
    if process.returncode or not match:
        raise AgentCutError("could not measure dialogue-isolation channels")
    return -120.0 if match.group(1) == "-inf" else float(match.group(1))


def isolation_confidence(center_db: float, side_db: float) -> float:
    """Conservative center-vocal likelihood, not a clean-voice guarantee."""
    dominance = center_db - side_db
    # Center dominance proves only that content is center-panned. It cannot
    # distinguish voice from center-panned music/SFX, so this deterministic
    # method is deliberately capped below the default registration threshold.
    likelihood = max(0.0, min(0.65, (dominance + 3.0) / 24.0))
    return round(likelihood, 3)


def isolate_dialogue(ffmpeg: str, ffprobe: str, source: str, output: str, report: str,
                     *, threshold: float = 0.8, overwrite: bool = False) -> dict[str, Any]:
    src, dst, report_path = Path(source).resolve(), Path(output).resolve(), Path(report).resolve()
    if src.suffix.lower() != ".wav":
        raise AgentCutError("dialogue-isolate currently accepts WAV input only")
    if not src.is_file():
        raise AgentCutError(f"input WAV not found: {src}")
    if (dst.exists() or report_path.exists()) and not overwrite:
        raise AgentCutError("output or report exists; pass --overwrite to replace")
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=channels,channel_layout,sample_rate,duration", "-of", "json", str(src)], capture_output=True, text=True)
    try:
        stream = json.loads(probe.stdout)["streams"][0]
        channels = int(stream["channels"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        raise AgentCutError("input WAV audio stream could not be probed")
    center_pan = "pan=mono|c0=0.5*FL+0.5*FR" if channels >= 2 else "pan=mono|c0=c0"
    side_pan = "pan=mono|c0=0.5*FL-0.5*FR" if channels >= 2 else "pan=mono|c0=0*c0"
    center_db = _mean_volume(ffmpeg, str(src), center_pan)
    side_db = _mean_volume(ffmpeg, str(src), side_pan)
    confidence = isolation_confidence(center_db, side_db) if channels >= 2 else 0.0
    dst.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run([
        ffmpeg, "-hide_banner", "-y" if overwrite else "-n", "-i", str(src),
        "-af", f"{center_pan},highpass=f=90,lowpass=f=9000,afftdn=nf=-25,dynaudnorm=f=150:g=9",
        "-ar", "48000", "-c:a", "pcm_s24le", str(dst),
    ], capture_output=True, text=True)
    if process.returncode:
        raise AgentCutError("dialogue isolation failed: " + "\n".join(process.stderr.splitlines()[-12:]))
    passed = confidence >= threshold
    result = {
        "version": "agentcut.dialogue-isolation-report.v1", "input": str(src), "vocalCandidate": str(dst),
        "method": "center-channel extraction + speech-band filtering + denoise",
        "separationConfidence": confidence, "confidenceThreshold": threshold, "separationPassed": passed,
        "registrationEligible": passed, "status": "REVIEW_REQUIRED" if passed else "SEPARATION_CONFIDENCE_FAILED",
        "contamination": {"centerMeanDb": center_db, "sideMeanDb": side_db,
                          "centerSideDominanceDb": round(center_db - side_db, 3),
                          "residualMusicOrEffectsPossible": True, "artifactRisk": "medium" if passed else "high"},
        "limitations": ["This deterministic local method is not source separation.",
                        "A passing score still requires listening review before voice registration.",
                        "A failing score must never be described as clean or registration-ready."],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
