#!/usr/bin/env python3
"""Build AgentCut's curated short-drama shot-recipe registry deterministically."""

from __future__ import annotations

import json
from pathlib import Path


UPSTREAM_REPO = "https://github.com/Vincentwei1021/video-shotcraft"
UPSTREAM_COMMIT = "d4915443232e89527fdc9d7e79f132ba411fc440"


SPECS = [
    ("camera.slow_push_in", "Slow push-in that accumulates pressure before a decisive cut.", "camera/tension-camera-moves.md", 0.25, 0.72, (2.5, 4.0, 5.5), "slow_push_in", "forward", "tension_peak"),
    ("camera.pull_back_isolation", "Pull back to isolate one subject as surrounding context falls away.", "camera/tension-camera-moves.md", 0.50, 0.18, (3.0, 4.5, 6.0), "pull_back", "backward", "isolation_result"),
    ("camera.dutch_roll_to_level", "Roll an unstable frame back to level to mark correction or regained control.", "camera/tension-camera-moves.md", 0.62, 0.42, (2.0, 3.5, 5.0), "dutch_roll", "clockwise_to_level", "level_contact"),
    ("camera.bullet_time_orbit", "Freeze subject action while camera motion examines a decisive instant.", "camera/tension-camera-moves.md", 0.70, 0.82, (3.0, 4.5, 6.0), "orbit", "lateral_arc", "freeze_contact"),
    ("camera.crash_zoom_punch", "Force attention from an establishing frame into a decisive detail.", "camera/crash-zoom-punch.md", 0.42, 0.92, (1.5, 2.5, 4.0), "crash_zoom", "forward", "zoom_contact"),
    ("camera.overhead_reveal", "Use a changing overhead angle to reveal space, evidence, or arrangement.", "camera/overhead-camera-moves.md", 0.22, 0.60, (3.0, 4.5, 6.0), "tilt_reveal", "overhead_to_level", "reveal_contact"),
    ("camera.tabletop_drop", "Survey an arrangement from above, then commit to one target.", "camera/overhead-camera-moves.md", 0.38, 0.76, (3.0, 4.5, 6.0), "tabletop_drop", "pan_then_drop", "target_contact"),
    ("camera.crane_rise_reveal", "Move from a readable detail to a wider spatial revelation.", "opening/crane-rise-reveal.md", 0.30, 0.66, (3.5, 5.0, 6.5), "crane_rise", "up_and_back", "wide_result"),
    ("camera.drone_dive_landing", "Descend from global context to one dramatic subject or clue.", "camera/space-camera-moves.md", 0.48, 0.82, (3.0, 4.5, 6.0), "drone_dive", "down_and_forward", "landing_contact"),
    ("camera.graze_face_tour", "Graze across face or object details while preserving a stable subject anchor.", "camera/graze-face-tour.md", 0.32, 0.55, (3.0, 4.5, 6.5), "lateral_graze", "left_to_right", "detail_result"),
    ("camera.steep_tilt_glide", "Glide through a steep tilt to make entry or discovery feel physically motivated.", "camera/steep-tilt-glide.md", 0.35, 0.68, (2.5, 4.0, 5.5), "tilt_glide", "diagonal", "glide_contact"),
    ("camera.depth_layer_parallax", "Separate foreground, subject, and background motion to reveal depth without a cut.", "camera/depth-layer-moves.md", 0.26, 0.54, (3.0, 5.0, 7.0), "parallax", "lateral", "depth_result"),
    ("rhythm.speed_ramp_focus", "Accelerate through setup, slow for the informative action, then recover speed.", "rhythm/speed-ramp-freeze.md", 0.55, 0.72, (3.0, 4.5, 6.0), "speed_ramp", "forward", "focus_contact"),
    ("rhythm.freeze_annotate", "Freeze a decisive frame long enough for an explicit visual annotation or clue read.", "rhythm/speed-ramp-freeze.md", 0.48, 0.58, (3.0, 4.5, 6.0), "freeze", "none", "annotation_contact"),
    ("rhythm.blackout_slam", "Use one evidence-backed intentional blackout as silence before a climax impact.", "rhythm/montage-rhythm-moves.md", 0.58, 0.95, (3.0, 4.3, 5.5), "slam", "forward", "slam_contact"),
    ("rhythm.wright_triple_cut", "Compress a three-step physical process into three readable close-up contacts.", "rhythm/montage-rhythm-moves.md", 0.48, 0.82, (2.5, 4.3, 5.5), "triple_cut", "matched_center", "third_contact"),
    ("rhythm.domino_cascade", "Carry visible force from one action result into the next setup.", "rhythm/montage-rhythm-moves.md", 0.40, 0.78, (3.0, 5.0, 6.5), "cascade", "causal_chain", "chain_contact"),
    ("rhythm.beat_cut_accelerando", "Shorten successive shot intervals to increase urgency toward a beat.", "rhythm/beat-cut-moves.md", 0.34, 0.86, (2.5, 4.5, 7.0), "accelerando_cuts", "forward", "final_beat"),
    ("rhythm.interrupt_reset", "Interrupt an established cadence once to signal new information or a power shift.", "rhythm/rhythm-interrupt-moves.md", 0.52, 0.40, (2.0, 3.5, 5.0), "rhythm_interrupt", "stop_then_resume", "interrupt_contact"),
    ("rhythm.trailer_tension_release", "Stage setup, compression, and release as a compact trailer grammar.", "rhythm/trailer-grammar-moves.md", 0.28, 0.90, (4.0, 6.0, 9.0), "tension_release", "forward", "release_contact"),
    ("transition.invisible_foreground_cut", "Hide one cut inside a fully occluding motivated foreground pass.", "transition/transition-hidden-cut.md", 0.50, 0.52, (1.0, 2.0, 3.0), "occlusion_pass", "lateral", "occlusion_contact"),
    ("transition.light_leak_hidden_cut", "Hide a cut at a controlled light peak without treating light as decoration.", "transition/transition-hidden-cut.md", 0.42, 0.60, (1.5, 2.5, 4.0), "light_peak", "diagonal", "light_contact"),
    ("transition.circle_match_iris", "Match subject position through a circular iris for a motivated spatial handoff.", "transition/circle-match-iris.md", 0.38, 0.58, (1.0, 2.0, 3.0), "iris", "inward_then_out", "iris_contact"),
    ("transition.page_turn", "Use a physical page turn only when paper, dossier, or chapter semantics justify it.", "transition/page-turn-transitions.md", 0.34, 0.50, (1.5, 2.5, 4.0), "page_turn", "right_to_left", "page_contact"),
    ("title.paper_title_card", "Hold a chapter title on a materially motivated paper card before returning to action.", "typography/paper-title-card.md", 0.24, 0.35, (1.5, 2.5, 4.0), "title_hold", "none", "title_contact"),
    ("title.marker_underline", "Underline one exact phrase as a beat anchor instead of decorating all text.", "typography/marker-underline-title.md", 0.30, 0.48, (1.5, 2.5, 4.0), "underline_draw", "left_to_right", "underline_contact"),
    ("outro.brand_morph", "Resolve a recurring story object into the approved brand mark at the end card.", "outro/ui-to-brand-morph.md", 0.42, 0.28, (3.0, 4.5, 6.0), "brand_morph", "inward", "brand_contact"),
]


def make_recipe(spec: tuple) -> dict:
    recipe_id, intent, source_path, before, after, duration, motion_type, direction, beat = spec
    setup_end = 0.22
    contact_end = 0.72
    cues = [{
        "cue_id": "primary_contact", "semantic": "editorial contact accent",
        "phase_id": "contact", "offset_seconds": 0,
        "asset_path": None, "license": None, "license_status": "symbolic_only",
    }]
    transition_intent = {
        "kind": "within_shot" if not recipe_id.startswith("transition.") else "between_shots",
        "intentional_black": None,
    }
    if recipe_id == "rhythm.blackout_slam":
        transition_intent["intentional_black"] = {
            "reference_fps": 30, "reference_start_frame": 48,
            "reference_duration_frames": 12,
            "reason": "one silent blackout beat accumulates pressure before the unique climax slam",
            "approval_policy": "release_gate_required",
        }
        cues = [{
            "cue_id": "slam_contact", "semantic": "climax impact accent",
            "phase_id": "contact", "offset_seconds": 0,
            "asset_path": None, "license": None, "license_status": "symbolic_only",
        }]
    return {
        "schema": "agentcut.shot_recipe.v1",
        "recipe_id": recipe_id, "version": "1.0.0",
        "source": {
            "repository": UPSTREAM_REPO, "commit": UPSTREAM_COMMIT,
            "path": f"references/shots/{source_path}",
            "adaptation": "structure and motion-language study; no Remotion code or media copied",
        },
        "license": {"spdx": "Apache-2.0", "notice": "NOTICE", "audio_included": False},
        "dramatic_intent": intent,
        "applicability": {
            "media_kinds": ["live_action", "generated_short_drama", "hybrid"],
            "ui_only": False, "default_short_drama_registry": True,
        },
        "energy_before": before, "energy_after": after,
        "suggested_duration": {"min_seconds": duration[0], "target_seconds": duration[1], "max_seconds": duration[2]},
        "camera_motion": {"type": motion_type, "direction": direction, "intensity": round(max(before, after), 2)},
        "motion_arc": {"phases": [
            {"phase_id": "setup", "start_ratio": 0.0, "end_ratio": setup_end, "description": "establish subject and causal setup", "camera_state": {"energy": before}},
            {"phase_id": "contact", "start_ratio": setup_end, "end_ratio": contact_end, "description": "execute the named camera/action contact", "camera_state": {"energy": max(before, after)}},
            {"phase_id": "result", "start_ratio": contact_end, "end_ratio": 1.0, "description": "hold the changed state long enough to read", "camera_state": {"energy": after}},
        ]},
        "subject_anchor": {"x_ratio": 0.5, "y_ratio": 0.46, "tolerance_ratio": 0.18, "safe_for_9x16": True},
        "action": {"setup": "establish a readable pre-action state", "contact": "show the decisive physical or editorial contact", "result": "show a visibly changed state"},
        "planned_hold": {"windows": [{"phase_id": "result_read", "hold_id": "result_read", "start_ratio": 0.82, "end_ratio": 1.0, "reason": "result readability"}]},
        "transition_intent": transition_intent,
        "beat_anchor": {"phase_id": beat if beat in {"setup", "contact", "result"} else "contact", "semantic": beat},
        "sfx_cues": cues,
        "known_pitfalls": [
            "do not use the recipe to excuse missing story information",
            "do not stack another recipe with the same dominant motion family on the same clip",
            "review normal-speed playback; still-frame novelty is not acceptance",
        ],
        "qa_contract": {
            "required_checks": ["source_admission", "narrative_gate", "cadence", "black_frame", "dialogue_coverage", "audio_safety"],
            "reject_unmotivated_hold": True, "preserve_existing_hard_gates": True,
        },
        "rollback": {
            "strategy": "remove the shot_recipe reference or restore the prior clip metadata, then recompile and rerender",
            "source_media_modified": False, "platform_mutation_authorized": False,
        },
    }


def build() -> dict:
    recipes = [make_recipe(spec) for spec in SPECS]
    return {
        "schema": "agentcut.shot_recipe_registry.v1",
        "registry_id": "agentcut.short_drama.director_recipes", "version": "1.0.0",
        "source": {"repository": UPSTREAM_REPO, "commit": UPSTREAM_COMMIT},
        "license": {"spdx": "Apache-2.0", "notice": "NOTICE"},
        "selection_policy": {
            "target": "live-action and generated short drama",
            "ui_only_default": False, "remotion_dependency": False,
            "audio_assets_imported": False,
            "layer": "per_shot_director_execution",
            "style_template_behavior": "preserve_project_style",
            "style_override_allowed": False,
        },
        "recipes": recipes,
    }


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[1] / "agentcut" / "shot_recipes" / "short_drama_v1.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination)
