from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from .models import Project


REGISTRY_ID = "agentcut.short_drama.director_recipes"
REGISTRY_VERSION = "1.0.0"
RECIPE_SCHEMA = "agentcut.shot_recipe.v1"
REGISTRY_SCHEMA = "agentcut.shot_recipe_registry.v1"
ALLOWED_BLACK_APPROVAL_POLICIES = {
    "qa_required", "release_gate_required", "non_release_only",
}
PROTECTED_OVERRIDE_FIELDS = {"recipe_id", "version", "source", "license"}
REQUIRED_RECIPE_FIELDS = (
    "recipe_id", "version", "source", "license", "dramatic_intent", "applicability",
    "energy_before", "energy_after", "suggested_duration", "camera_motion", "motion_arc",
    "subject_anchor", "action", "planned_hold", "transition_intent", "beat_anchor",
    "sfx_cues", "known_pitfalls", "qa_contract", "rollback",
)


@dataclass(frozen=True)
class RecipeProblem:
    code: str
    message: str
    track_id: str | None = None
    track_index: int | None = None
    clip_index: int | None = None
    clip_id: str | None = None
    recipe_id: str | None = None
    phase_id: str | None = None
    time_range: dict[str, float] | None = None
    related_clips: list[dict[str, Any]] | None = None


def _round_frame(seconds: float, fps: int) -> int:
    return max(0, math.floor(seconds * fps + 0.5))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _registry_path() -> Path:
    return Path(str(files("agentcut").joinpath("shot_recipes/short_drama_v1.json")))


def load_builtin_registry() -> tuple[dict[str, Any], str, str]:
    path = _registry_path()
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("shot recipe registry must be an object")
    if value.get("schema") != REGISTRY_SCHEMA:
        raise ValueError("unsupported built-in shot recipe registry schema")
    if value.get("registry_id") != REGISTRY_ID or value.get("version") != REGISTRY_VERSION:
        raise ValueError("built-in shot recipe registry identity/version mismatch")
    recipes = value.get("recipes")
    if not isinstance(recipes, list) or not 20 <= len(recipes) <= 30:
        raise ValueError("short-drama registry must contain 20-30 curated recipes")
    identities = [(item.get("recipe_id"), item.get("version")) for item in recipes if isinstance(item, dict)]
    if len(identities) != len(recipes) or len(set(identities)) != len(identities):
        raise ValueError("shot recipe registry contains invalid or duplicate identities")
    for recipe in recipes:
        problems = _shape_problems(recipe, "REGISTRY_RECIPE")
        if problems:
            raise ValueError(f"invalid built-in recipe {recipe.get('recipe_id')}: {problems[0][1]}")
    return value, str(path), _sha256(path)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _override_paths(value: dict[str, Any], prefix: str = "") -> list[str]:
    paths: list[str] = []
    for key, item in sorted(value.items()):
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            paths.extend(_override_paths(item, path))
        else:
            paths.append(path)
    return paths


def _recipe_reference(metadata: dict[str, Any]) -> dict[str, Any] | None:
    nested = metadata.get("shot_recipe")
    if nested is not None:
        return nested if isinstance(nested, dict) else {"__invalid__": nested}
    if "recipe_id" in metadata or "recipe_version" in metadata or "shot_recipe_override" in metadata:
        return {
            "recipe_id": metadata.get("recipe_id"),
            "version": metadata.get("recipe_version"),
            "override": metadata.get("shot_recipe_override", {}),
        }
    return None


def _shape_problems(recipe: dict[str, Any], prefix: str = "SHOT_RECIPE") -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    missing = [field for field in REQUIRED_RECIPE_FIELDS if field not in recipe]
    if missing:
        problems.append((f"{prefix}_REQUIRED_FIELDS_MISSING", "missing fields: " + ", ".join(missing)))
        return problems
    for field in ("recipe_id", "version", "dramatic_intent"):
        if not isinstance(recipe.get(field), str) or not recipe[field].strip():
            problems.append((f"{prefix}_{field.upper()}_INVALID", f"{field} must be a non-empty string"))
    for field in ("source", "license", "applicability", "suggested_duration", "camera_motion", "motion_arc",
                  "subject_anchor", "action", "planned_hold", "transition_intent", "beat_anchor", "qa_contract", "rollback"):
        if not isinstance(recipe.get(field), dict):
            problems.append((f"{prefix}_{field.upper()}_INVALID", f"{field} must be an object"))
    for field in ("energy_before", "energy_after"):
        value = recipe.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            problems.append((f"{prefix}_{field.upper()}_INVALID", f"{field} must be between 0 and 1"))
    if not isinstance(recipe.get("sfx_cues"), list):
        problems.append((f"{prefix}_SFX_CUES_INVALID", "sfx_cues must be an array"))
    if not isinstance(recipe.get("known_pitfalls"), list) or any(not isinstance(x, str) or not x for x in recipe.get("known_pitfalls", [])):
        problems.append((f"{prefix}_KNOWN_PITFALLS_INVALID", "known_pitfalls must be non-empty strings"))
    duration = recipe.get("suggested_duration")
    if isinstance(duration, dict):
        values = [duration.get(x) for x in ("min_seconds", "target_seconds", "max_seconds")]
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or x <= 0 for x in values):
            problems.append((f"{prefix}_SUGGESTED_DURATION_INVALID", "suggested duration values must be positive numbers"))
        elif not values[0] <= values[1] <= values[2]:
            problems.append((f"{prefix}_SUGGESTED_DURATION_ORDER_INVALID", "suggested duration must satisfy min <= target <= max"))
    license_value = recipe.get("license")
    if isinstance(license_value, dict) and license_value.get("spdx") != "Apache-2.0":
        problems.append((f"{prefix}_LICENSE_UNAPPROVED", "production registry recipe license must be Apache-2.0"))
    applicability = recipe.get("applicability")
    if isinstance(applicability, dict):
        kinds = applicability.get("media_kinds")
        if not isinstance(kinds, list) or not kinds or any(x not in {"live_action", "generated_short_drama", "hybrid"} for x in kinds):
            problems.append((f"{prefix}_APPLICABILITY_INVALID", "media_kinds must contain approved short-drama media kinds"))
        if applicability.get("ui_only") is True:
            problems.append((f"{prefix}_UI_ONLY_FORBIDDEN", "UI-only recipes cannot enter the default short-drama registry"))
    return problems


def _interval(
    raw: dict[str, Any], clip_start: float, clip_duration: float, fps: int,
    *, code_prefix: str, phase_id: str | None,
) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    has_seconds = "start_seconds" in raw or "end_seconds" in raw
    has_ratios = "start_ratio" in raw or "end_ratio" in raw
    if has_seconds and has_ratios:
        return None, (f"{code_prefix}_TIME_WINDOW_AMBIGUOUS", "use seconds or ratios, not both")
    if has_seconds:
        start, end = raw.get("start_seconds"), raw.get("end_seconds")
    elif has_ratios:
        start_ratio, end_ratio = raw.get("start_ratio"), raw.get("end_ratio")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in (start_ratio, end_ratio)):
            return None, (f"{code_prefix}_TIME_WINDOW_INVALID", "ratio window requires numeric start_ratio and end_ratio")
        start, end = float(start_ratio) * clip_duration, float(end_ratio) * clip_duration
    else:
        return None, (f"{code_prefix}_TIME_WINDOW_MISSING", "window requires start/end seconds or ratios")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in (start, end)):
        return None, (f"{code_prefix}_TIME_WINDOW_INVALID", "window bounds must be numeric")
    start, end = float(start), float(end)
    if start < 0 or end <= start:
        return None, (f"{code_prefix}_TIME_WINDOW_INVALID", "window must satisfy 0 <= start < end")
    if end > clip_duration + 1e-9:
        return None, (f"{code_prefix}_OUT_OF_CLIP", f"window ends at {end:g}s after clip duration {clip_duration:g}s")
    absolute_start, absolute_end = clip_start + start, clip_start + end
    start_frame, end_frame = _round_frame(absolute_start, fps), _round_frame(absolute_end, fps)
    if end_frame <= start_frame:
        end_frame = start_frame + 1
    return {
        "phaseId": phase_id,
        "clipTime": {"start": start, "end": end, "duration": end - start},
        "timelineTime": {"start": absolute_start, "end": absolute_end, "duration": end - start},
        "frameRange": {"startFrame": start_frame, "endFrameExclusive": end_frame, "frameCount": end_frame - start_frame},
    }, None


def _materialize_one(
    recipe: dict[str, Any], *, clip: Any, track_id: str, track_index: int, clip_index: int,
    fps: int, registry_path: str, registry_sha: str, project_override: dict[str, Any], clip_override: dict[str, Any],
) -> tuple[list[RecipeProblem], dict[str, Any]]:
    problems: list[RecipeProblem] = []
    recipe_id = recipe.get("recipe_id")

    def problem(code: str, message: str, *, phase_id: str | None = None, time_range: dict[str, float] | None = None) -> None:
        problems.append(RecipeProblem(code, message, track_id, track_index, clip_index, clip.id, recipe_id, phase_id, time_range))

    for code, message in _shape_problems(recipe):
        problem(code, message)
    phase_values = recipe.get("motion_arc", {}).get("phases", []) if isinstance(recipe.get("motion_arc"), dict) else []
    if not isinstance(phase_values, list) or not phase_values:
        problem("SHOT_RECIPE_MOTION_ARC_MISSING", "motion_arc.phases must contain at least one phase")
        phase_values = []
    phases: list[dict[str, Any]] = []
    phase_ids: set[str] = set()
    last_end = 0.0
    for index, raw in enumerate(phase_values):
        if not isinstance(raw, dict):
            problem("SHOT_RECIPE_MOTION_PHASE_INVALID", f"motion_arc.phases[{index}] must be an object")
            continue
        phase_id = raw.get("phase_id")
        if not isinstance(phase_id, str) or not phase_id:
            problem("SHOT_RECIPE_MOTION_PHASE_ID_MISSING", f"motion_arc.phases[{index}] requires phase_id")
            continue
        if phase_id in phase_ids:
            problem("SHOT_RECIPE_MOTION_PHASE_DUPLICATE", f"duplicate phase_id {phase_id}", phase_id=phase_id)
            continue
        phase_ids.add(phase_id)
        interval, error = _interval(raw, clip.start, clip.duration, fps, code_prefix="SHOT_RECIPE_MOTION_ARC", phase_id=phase_id)
        if error:
            problem(error[0], error[1], phase_id=phase_id)
            continue
        assert interval is not None
        if interval["clipTime"]["start"] < last_end - 1e-9:
            problem("SHOT_RECIPE_MOTION_ARC_OVERLAP", "motion phases must be ordered and non-overlapping", phase_id=phase_id, time_range=interval["timelineTime"])
        last_end = max(last_end, interval["clipTime"]["end"])
        phases.append({**interval, "description": raw.get("description"), "cameraState": raw.get("camera_state", {})})
    phase_map = {item["phaseId"]: item for item in phases}

    holds: list[dict[str, Any]] = []
    planned_hold = recipe.get("planned_hold")
    windows = planned_hold.get("windows", []) if isinstance(planned_hold, dict) else []
    if not isinstance(windows, list):
        problem("SHOT_RECIPE_PLANNED_HOLD_INVALID", "planned_hold.windows must be an array")
        windows = []
    for index, raw in enumerate(windows):
        if not isinstance(raw, dict):
            problem("SHOT_RECIPE_PLANNED_HOLD_INVALID", f"planned_hold.windows[{index}] must be an object")
            continue
        hold_id = raw.get("hold_id", f"hold-{index}")
        interval, error = _interval(raw, clip.start, clip.duration, fps, code_prefix="SHOT_RECIPE_PLANNED_HOLD", phase_id=str(hold_id))
        if error:
            problem(error[0], error[1], phase_id=str(hold_id))
        elif interval:
            holds.append({**interval, "reason": raw.get("reason")})

    cues: list[dict[str, Any]] = []
    sfx_values = recipe.get("sfx_cues", [])
    if isinstance(sfx_values, list):
        for index, cue in enumerate(sfx_values):
            if not isinstance(cue, dict):
                problem("SHOT_RECIPE_SFX_CUE_INVALID", f"sfx_cues[{index}] must be an object")
                continue
            cue_id = cue.get("cue_id")
            if not isinstance(cue_id, str) or not cue_id:
                problem("SHOT_RECIPE_SFX_CUE_ID_MISSING", f"sfx_cues[{index}] requires cue_id")
                continue
            at_seconds = cue.get("at_seconds")
            phase_id = cue.get("phase_id")
            if at_seconds is None and isinstance(phase_id, str) and phase_id in phase_map:
                at_seconds = phase_map[phase_id]["clipTime"]["start"] + float(cue.get("offset_seconds", 0))
            if isinstance(at_seconds, bool) or not isinstance(at_seconds, (int, float)):
                problem("SHOT_RECIPE_SFX_CUE_TIME_MISSING", f"SFX cue {cue_id} needs at_seconds or a valid phase_id", phase_id=phase_id if isinstance(phase_id, str) else None)
                continue
            at_seconds = float(at_seconds)
            if at_seconds < 0 or at_seconds > clip.duration + 1e-9:
                problem("SHOT_RECIPE_SFX_CUE_OUT_OF_CLIP", f"SFX cue {cue_id} at {at_seconds:g}s is outside clip duration {clip.duration:g}s", phase_id=phase_id if isinstance(phase_id, str) else None)
                continue
            asset_path = cue.get("asset_path")
            cue_license = cue.get("license")
            if asset_path is not None:
                verified = isinstance(cue_license, dict) and cue_license.get("verified") is True and all(
                    isinstance(cue_license.get(key), str) and cue_license[key] for key in ("spdx", "source_url", "sha256")
                )
                if not verified:
                    problem("SHOT_RECIPE_SFX_LICENSE_UNVERIFIED", f"SFX cue {cue_id} cannot bind an asset without verified per-file license evidence")
            absolute = clip.start + at_seconds
            cues.append({
                "cueId": cue_id, "semantic": cue.get("semantic"), "phaseId": phase_id,
                "clipTimeSeconds": at_seconds, "timelineTimeSeconds": absolute,
                "frame": _round_frame(absolute, fps), "assetPath": asset_path,
                "license": cue_license, "symbolicOnly": asset_path is None,
            })

    intentional_black = recipe.get("transition_intent", {}).get("intentional_black") if isinstance(recipe.get("transition_intent"), dict) else None
    black_manifest = None
    if intentional_black:
        if not isinstance(intentional_black, dict):
            problem("SHOT_RECIPE_INTENTIONAL_BLACK_EVIDENCE_REQUIRED", "intentional_black must be a complete evidence object")
        else:
            ref_fps = intentional_black.get("reference_fps")
            ref_start = intentional_black.get("reference_start_frame")
            ref_duration = intentional_black.get("reference_duration_frames")
            reason = intentional_black.get("reason")
            approval = intentional_black.get("approval_policy")
            valid_numbers = (
                isinstance(ref_fps, int) and not isinstance(ref_fps, bool) and ref_fps > 0 and
                isinstance(ref_start, int) and not isinstance(ref_start, bool) and ref_start >= 0 and
                isinstance(ref_duration, int) and not isinstance(ref_duration, bool) and ref_duration > 0
            )
            if not valid_numbers or not isinstance(reason, str) or not reason.strip() or approval not in ALLOWED_BLACK_APPROVAL_POLICIES:
                problem("SHOT_RECIPE_INTENTIONAL_BLACK_EVIDENCE_REQUIRED", "intentional black requires exact reference fps/start/duration frames, a reason, and an approved policy")
            else:
                start_seconds = ref_start / ref_fps
                duration_seconds = ref_duration / ref_fps
                end_seconds = start_seconds + duration_seconds
                if end_seconds > clip.duration + 1e-9:
                    problem("SHOT_RECIPE_INTENTIONAL_BLACK_OUT_OF_CLIP", f"intentional black ends at {end_seconds:g}s after clip duration {clip.duration:g}s")
                else:
                    absolute_start = clip.start + start_seconds
                    absolute_end = clip.start + end_seconds
                    output_start = _round_frame(absolute_start, fps)
                    output_end = _round_frame(absolute_end, fps)
                    black_manifest = {
                        "reason": reason, "approvalPolicy": approval,
                        "reference": {"fps": ref_fps, "startFrame": ref_start, "durationFrames": ref_duration},
                        "clipTime": {"start": start_seconds, "end": end_seconds, "duration": duration_seconds},
                        "timelineTime": {"start": absolute_start, "end": absolute_end, "duration": duration_seconds},
                        "frameRange": {"startFrame": output_start, "endFrameExclusive": output_end, "frameCount": output_end-output_start},
                    }
    if clip.metadata.get("intentional_black") is True and black_manifest is None:
        problem("SHOT_RECIPE_INTENTIONAL_BLACK_EVIDENCE_REQUIRED", "clip declares intentional_black but no exact recipe evidence was materialized")

    materialized = {
        "clipId": clip.id, "trackId": track_id, "trackIndex": track_index, "clipIndex": clip_index,
        "recipeId": recipe_id, "recipeVersion": recipe.get("version"),
        "clipTimeRange": {"start": 0.0, "end": clip.duration, "duration": clip.duration},
        "timelineTimeRange": {"start": clip.start, "end": clip.start + clip.duration, "duration": clip.duration},
        "frameRange": {
            "startFrame": _round_frame(clip.start, fps),
            "endFrameExclusive": _round_frame(clip.start + clip.duration, fps),
            "frameCount": _round_frame(clip.start + clip.duration, fps) - _round_frame(clip.start, fps),
        },
        "motionArc": {"phases": phases}, "plannedHold": {"windows": holds}, "sfxCues": cues,
        "intentionalBlack": black_manifest, "resolvedRecipe": recipe,
        "provenance": {
            "registryId": REGISTRY_ID, "registryVersion": REGISTRY_VERSION,
            "registryPath": registry_path, "registrySha256": registry_sha,
            "projectOverride": project_override, "clipOverride": clip_override,
            "projectOverridePaths": _override_paths(project_override),
            "clipOverridePaths": _override_paths(clip_override),
            "secondsAuthoritative": True, "frameRounding": "nearest-half-up", "outputFps": fps,
            "remotionRequired": False, "audioAssetsImported": False,
        },
        "rollback": recipe.get("rollback"),
    }
    return problems, materialized


def validate_and_materialize_shot_recipes(project: Project) -> tuple[list[RecipeProblem], dict[str, Any]]:
    registry, registry_path, registry_sha = load_builtin_registry()
    policy = project.shot_recipe_policy or {}
    references = []
    for track_index, track in enumerate(project.video_tracks):
        if track.enabled:
            for clip_index, clip in enumerate(track.clips):
                reference = _recipe_reference(clip.metadata)
                if reference is not None:
                    references.append((track_index, clip_index, track, clip, reference))
    enabled = bool(references or policy.get("enabled", False))
    base = {
        "enabled": enabled, "registryId": REGISTRY_ID, "registryVersion": REGISTRY_VERSION,
        "registryPath": registry_path, "registrySha256": registry_sha,
        "recipeCount": len(registry.get("recipes", [])), "referencedClipCount": len(references),
        "secondsAuthoritative": True, "frameRounding": "nearest-half-up", "outputFps": project.output.fps,
        "remotionRequired": False, "audioAssetsImported": False,
        "layer": "per_shot_director_execution", "styleTemplateBehavior": "preserve_project_style",
        "styleOverrideAllowed": False,
    }
    if not enabled:
        return [], {**base, "status": "NOT_REQUESTED", "materializedTimeline": [], "repairTasks": []}
    problems: list[RecipeProblem] = []
    registry_id = policy.get("registryId", REGISTRY_ID)
    registry_version = policy.get("registryVersion", REGISTRY_VERSION)
    if registry_id != REGISTRY_ID:
        problems.append(RecipeProblem("SHOT_RECIPE_REGISTRY_UNKNOWN", f"unknown registry {registry_id!r}"))
    if registry_version != REGISTRY_VERSION:
        problems.append(RecipeProblem("SHOT_RECIPE_REGISTRY_VERSION_UNSUPPORTED", f"registry version must be {REGISTRY_VERSION}"))
    project_overrides = policy.get("projectOverrides", {})
    if not isinstance(project_overrides, dict):
        problems.append(RecipeProblem("SHOT_RECIPE_PROJECT_OVERRIDES_INVALID", "shotRecipePolicy.projectOverrides must be an object"))
        project_overrides = {}
    by_id = {item.get("recipe_id"): item for item in registry.get("recipes", []) if isinstance(item, dict)}
    materialized: list[dict[str, Any]] = []
    for track_index, clip_index, track, clip, reference in references:
        common = dict(track_id=track.id, track_index=track_index, clip_index=clip_index, clip_id=clip.id)
        if "__invalid__" in reference:
            problems.append(RecipeProblem("SHOT_RECIPE_REFERENCE_INVALID", "metadata.shot_recipe must be an object", **common))
            continue
        recipe_id, version = reference.get("recipe_id"), reference.get("version")
        if not isinstance(recipe_id, str) or not recipe_id:
            problems.append(RecipeProblem("SHOT_RECIPE_ID_MISSING", "shot recipe reference requires recipe_id", **common))
            continue
        if not isinstance(version, str) or not version:
            problems.append(RecipeProblem("SHOT_RECIPE_VERSION_MISSING", "shot recipe reference requires an explicit version", recipe_id=recipe_id, **common))
            continue
        recipe = by_id.get(recipe_id)
        if recipe is None:
            problems.append(RecipeProblem("SHOT_RECIPE_UNKNOWN", f"unknown recipe_id {recipe_id!r}", recipe_id=recipe_id, **common))
            continue
        if version != recipe.get("version"):
            problems.append(RecipeProblem("SHOT_RECIPE_VERSION_MISMATCH", f"recipe {recipe_id} requires version {recipe.get('version')}", recipe_id=recipe_id, **common))
            continue
        project_override = project_overrides.get(recipe_id, {})
        clip_override = reference.get("override", {})
        if not isinstance(project_override, dict):
            problems.append(RecipeProblem("SHOT_RECIPE_PROJECT_OVERRIDE_INVALID", "project recipe override must be an object", recipe_id=recipe_id, **common))
            project_override = {}
        if not isinstance(clip_override, dict):
            problems.append(RecipeProblem("SHOT_RECIPE_CLIP_OVERRIDE_INVALID", "clip recipe override must be an object", recipe_id=recipe_id, **common))
            clip_override = {}
        forbidden = sorted((set(project_override) | set(clip_override)) & PROTECTED_OVERRIDE_FIELDS)
        if forbidden:
            problems.append(RecipeProblem("SHOT_RECIPE_OVERRIDE_PROVENANCE_FORBIDDEN", "overrides cannot change " + ", ".join(forbidden), recipe_id=recipe_id, **common))
            continue
        resolved = _merge(_merge(recipe, project_override), clip_override)
        item_problems, item = _materialize_one(
            resolved, clip=clip, track_id=track.id, track_index=track_index, clip_index=clip_index,
            fps=project.output.fps, registry_path=registry_path, registry_sha=registry_sha,
            project_override=project_override, clip_override=clip_override,
        )
        problems.extend(item_problems)
        materialized.append(item)
    coverage = {
        **base, "status": "FAIL" if problems else "PASS",
        "materializedTimeline": materialized,
        "problemCount": len(problems),
        "problems": [asdict(item) for item in problems],
    }
    coverage["repairTasks"] = map_shot_recipe_repairs(project, problems=problems, materialized=materialized)
    return problems, coverage


def map_shot_recipe_repairs(
    project: Project, *, problems: list[RecipeProblem] | None = None,
    materialized: list[dict[str, Any]] | None = None,
    aggregate_problems: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if problems is None or materialized is None:
        problems, coverage = validate_and_materialize_shot_recipes(project)
        materialized = coverage.get("materializedTimeline", [])
    tasks: list[dict[str, Any]] = []
    by_clip = {item.get("clipId"): item for item in materialized if item.get("clipId")}
    for track_index, track in enumerate(project.video_tracks):
        if not track.enabled:
            continue
        for clip_index, clip in enumerate(track.clips):
            if not clip.id or clip.id in by_clip:
                continue
            reference = _recipe_reference(clip.metadata) or {}
            by_clip[clip.id] = {
                "clipId": clip.id, "trackId": track.id, "trackIndex": track_index, "clipIndex": clip_index,
                "recipeId": reference.get("recipe_id"), "recipeVersion": reference.get("version"),
                "timelineTimeRange": {"start": clip.start, "end": clip.start + clip.duration, "duration": clip.duration},
                "frameRange": {
                    "startFrame": _round_frame(clip.start, project.output.fps),
                    "endFrameExclusive": _round_frame(clip.start + clip.duration, project.output.fps),
                },
                "motionArc": {"phases": []},
                "rollback": {"strategy": "remove or correct this clip's shot_recipe metadata and revalidate", "source_media_modified": False},
            }

    def append_task(code: str, message: str, item: dict[str, Any], phase: dict[str, Any] | None, requested: dict[str, Any] | None = None) -> None:
        task_no = len(tasks) + 1
        tasks.append({
            "taskId": f"shot-recipe-repair-{task_no:04d}", "code": code, "message": message,
            "clipId": item.get("clipId"), "trackId": item.get("trackId"),
            "recipeId": item.get("recipeId"), "recipeVersion": item.get("recipeVersion"),
            "phaseId": phase.get("phaseId") if phase else None,
            "timeRange": (phase or {}).get("timelineTime", item.get("timelineTimeRange")),
            "frameRange": (phase or {}).get("frameRange", item.get("frameRange")),
            "requestedAggregateRange": requested,
            "rollback": item.get("rollback"),
            "action": "repair the named clip/recipe phase, then rerun validate, compile, render, and existing QA gates",
            "platformMutationAuthorized": False,
        })

    for problem in problems:
        item = by_clip.get(problem.clip_id)
        if not item:
            continue
        phases = item.get("motionArc", {}).get("phases", [])
        phase = next((value for value in phases if value.get("phaseId") == problem.phase_id), None)
        append_task(problem.code, problem.message, item, phase)
    for aggregate in aggregate_problems or []:
        if not isinstance(aggregate, dict):
            continue
        range_value = aggregate.get("timeRange") if isinstance(aggregate.get("timeRange"), dict) else aggregate
        start, end = range_value.get("start"), range_value.get("end")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            continue
        requested = {"start": float(start), "end": float(end), "duration": float(end)-float(start)}
        for item in materialized:
            clip_range = item.get("timelineTimeRange", {})
            if clip_range.get("start", 0) >= end or clip_range.get("end", 0) <= start:
                continue
            phases = [phase for phase in item.get("motionArc", {}).get("phases", [])
                      if phase.get("timelineTime", {}).get("start", 0) < end and phase.get("timelineTime", {}).get("end", 0) > start]
            if phases:
                for phase in phases:
                    append_task(str(aggregate.get("code") or "AGGREGATE_RECIPE_PROBLEM"), str(aggregate.get("message") or "aggregate issue intersects recipe phase"), item, phase, requested)
            else:
                append_task(str(aggregate.get("code") or "AGGREGATE_RECIPE_PROBLEM"), str(aggregate.get("message") or "aggregate issue intersects clip"), item, None, requested)
    return tasks


def list_short_drama_recipes() -> dict[str, Any]:
    registry, path, digest = load_builtin_registry()
    return {
        "registryId": registry.get("registry_id"), "registryVersion": registry.get("version"),
        "schema": registry.get("schema"), "path": path, "sha256": digest,
        "recipeCount": len(registry.get("recipes", [])),
        "recipes": [{
            "recipeId": item.get("recipe_id"), "version": item.get("version"),
            "dramaticIntent": item.get("dramatic_intent"), "applicability": item.get("applicability"),
            "source": item.get("source"), "license": item.get("license"),
        } for item in registry.get("recipes", [])],
        "remotionRequired": False, "audioAssetsImported": False,
        "layer": "per_shot_director_execution", "styleTemplateBehavior": "preserve_project_style",
        "styleOverrideAllowed": False,
    }
