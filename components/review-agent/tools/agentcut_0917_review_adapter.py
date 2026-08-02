#!/usr/bin/env python3
"""Adapt immutable AgentCut 0.9.17 evidence for Review Agent 1.0.0.

The adapter does not treat the render plan as an observation. Measured values
must be supplied separately and are bound to the exact candidate and sidecar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--measurements", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--project-version", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    sidecar = json.loads(args.sidecar.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    measurements = json.loads(args.measurements.read_text(encoding="utf-8"))
    media_sha = sha(args.media)
    sidecar_sha = sha(args.sidecar)
    registry_sha = sha(args.registry)

    assert sidecar["schema"] == "agentcut.materialized_shot_recipes.v1"
    assert sidecar["outputSha256"] == media_sha
    assert manifest["releaseGate"]["finalSha256"] == media_sha
    assert manifest["shotRecipes"]["sidecarSha256"] == sidecar_sha
    assert sidecar["registrySha256"] == registry_sha
    assert measurements["candidate_sha256"] == media_sha
    assert measurements["sidecar_sha256"] == sidecar_sha

    measured_by_clip = {row["clip_id"]: row["actual"] for row in measurements["clips"]}
    clips = []
    recipes = []
    render_clips = []
    beats = []
    cues = []
    for row in sidecar["materializedTimeline"]:
        clip_id = row["clipId"]
        resolved = row["resolvedRecipe"]
        fps = sidecar["outputFps"]
        frame_range = row["frameRange"]
        phases = row["motionArc"]["phases"]
        contact = next((phase for phase in phases if phase["phaseId"] == "contact"), phases[0])
        beat_id = f"{clip_id}:contact"
        hold_windows = row.get("plannedHold", {}).get("windows", [])
        hold_frames = max((window["frameRange"]["frameCount"] for window in hold_windows), default=0)
        planned_cues = []
        symbolic_only = True
        for cue in row.get("sfxCues", []):
            symbolic_only = symbolic_only and bool(cue.get("symbolicOnly"))
            if not cue.get("symbolicOnly"):
                planned_cues.append({
                    "cue_id": cue["cueId"],
                    "action_frame": cue["frame"],
                    "tolerance_frames": 2,
                })
                cues.append({"cue_id": cue["cueId"], "clip_id": clip_id, "frame": cue["frame"]})
        applicability = {
            "shot_recipe_conformance": "REQUIRED",
            "motion_arc_audit": "REQUIRED",
            "subject_anchor_audit": "REQUIRED",
            "beat_sync_audit": "REQUIRED",
            "sfx_cue_audit": "NOT_APPLICABLE" if symbolic_only else "REQUIRED",
            "readability_audit": "NOT_APPLICABLE",
        }
        intentional_effects = []
        black = row.get("intentionalBlack")
        if black:
            black_range = black["frameRange"]
            intentional_effects.append({
                "effect": "black",
                "start_frame": black_range["startFrame"],
                "end_frame": black_range["endFrameExclusive"] - 1,
                "reason": black["reason"],
                "approved_policy": black["approvalPolicy"],
            })
        recipe = {
            "recipe_id": row["recipeId"],
            "clip_id": clip_id,
            "applicability": applicability,
            "camera_motion": {
                **resolved["camera_motion"],
                "phases": [{"phase": phase["phaseId"]} for phase in phases],
                "max_curve_rmse": 0.05,
            },
            "subject_anchor": {
                "target": "materialized_primary_subject",
                "tolerance_px": round(resolved["subject_anchor"]["tolerance_ratio"] * 720, 3),
            },
            "action": {
                "required_phases": [phase for phase in ("setup", "contact", "result") if phase in resolved["action"]],
                "result_hold_frames": hold_frames,
            },
            "transition": {"beat_id": beat_id, "offset_frames": 0, "tolerance_frames": 2},
            "sfx_cues": planned_cues,
            "readability": [],
            "intentional_effects": intentional_effects,
            "source_schema": sidecar["schema"],
            "source_recipe_version": row["recipeVersion"],
        }
        timeline_range = row["timelineTimeRange"]
        clips.append({
            "clip_id": clip_id,
            "recipe_id": row["recipeId"],
            "fps": fps,
            "start_frame": frame_range["startFrame"],
            "end_frame": frame_range["endFrameExclusive"],
            "start_seconds": timeline_range["start"],
            "end_seconds": timeline_range["end"],
            "actual": measured_by_clip[clip_id],
        })
        recipes.append(recipe)
        render_clips.append({"clip_id": clip_id, "recipe_id": row["recipeId"]})
        beats.append({"beat_id": beat_id, "frame": contact["frameRange"]["startFrame"]})

    args.out_dir.mkdir(parents=True, exist_ok=True)
    timeline_path = args.out_dir / "materialized_timeline.json"
    common = {
        "candidate_sha256": media_sha,
        "project_id": args.project_id,
        "project_version": args.project_version,
    }
    write(timeline_path, {
        "schema": "qingshan.agentcut.materialized_timeline.adapter.v1",
        **common,
        "source_agentcut_schema": sidecar["schema"],
        "source_sidecar": str(args.sidecar.resolve()),
        "source_sidecar_sha256": sidecar_sha,
        "clips": clips,
    })
    timeline_sha = sha(timeline_path)
    provenance = {"timeline_provenance": {"timeline_evidence_sha256": timeline_sha}}
    write(args.out_dir / "render_plan.json", {**common, **provenance, "source_manifest_sha256": sha(args.manifest), "clips": render_clips})
    write(args.out_dir / "shot_recipe_registry.json", {**common, **provenance, "contract_version": "qingshan.agentcut.shot_recipe_contract_fixture.v1", "source_registry_sha256": registry_sha, "recipes": recipes})
    write(args.out_dir / "beat_grid.json", {**common, **provenance, "beats": beats})
    write(args.out_dir / "sfx_cue_manifest.json", {**common, **provenance, "cues": cues})
    write(args.out_dir / "adapter_receipt.json", {
        "schema": "qingshan.agentcut_0p9p17.review_1p0p0_adapter_receipt.v1",
        "status": "PASS",
        "candidate_sha256": media_sha,
        "sidecar_sha256": sidecar_sha,
        "manifest_sha256": sha(args.manifest),
        "registry_sha256": registry_sha,
        "measurement_sha256": sha(args.measurements),
        "timeline_evidence_sha256": timeline_sha,
        "project_id": args.project_id,
        "project_version": args.project_version,
        "source_schema": sidecar["schema"],
        "platform_mutation_authorized": False,
    })


if __name__ == "__main__":
    main()
