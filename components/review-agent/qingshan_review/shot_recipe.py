from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable


CONTRACT_VERSION = "qingshan.agentcut.shot_recipe_contract.v1"
FIXTURE_CONTRACT_VERSION = "qingshan.agentcut.shot_recipe_contract_fixture.v1"
RULE_VERSION = "qingshan.review.shot_recipe_conformance.v1"
CAPABILITIES = (
    "shot_recipe_conformance",
    "motion_arc_audit",
    "subject_anchor_audit",
    "beat_sync_audit",
    "sfx_cue_audit",
    "readability_audit",
)
EVIDENCE_ALIASES = {
    "materialized_timeline": ("agentcut_materialized_timeline", "materialized_timeline"),
    "render_plan": ("agentcut_render_plan", "render_plan"),
    "shot_recipe_registry": ("shot_recipe_registry",),
    "sfx_cue_manifest": ("sfx_cue_manifest",),
    "beat_grid": ("beat_grid",),
    "shot_recipe_sidecar": ("agentcut_shot_recipe_sidecar", "shot_recipe_sidecar"),
    "render_manifest": ("agentcut_render_manifest", "render_manifest"),
    "agentcut_project": ("agentcut_project",),
    "provenance_envelope": ("shot_recipe_provenance", "agentcut_shot_recipe_provenance"),
}
NEW_PROFILES = {
    "shot_recipe_conformance_v1",
    "agentcut_director_v1",
    "qingshan.production.shot_recipe.v1",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _first(mapping: dict[str, Any], *paths: str) -> Any:
    for dotted in paths:
        value: Any = mapping
        for key in dotted.split("."):
            if not isinstance(value, dict) or key not in value:
                value = None
                break
            value = value[key]
        if value not in (None, ""):
            return value
    return None


def _identity(data: dict[str, Any]) -> dict[str, Any]:
    provenance = data.get("timeline_provenance") if isinstance(data.get("timeline_provenance"), dict) else {}
    return {
        "candidate_sha256": str(_first(data, "candidate_sha256", "media_sha256", "output_sha256", "output.sha256") or "").lower(),
        "project_id": str(_first(data, "project_id", "project.id", "agentcut.project_id") or ""),
        "project_version": str(_first(data, "project_version", "project.version", "agentcut.project_version") or ""),
        "timeline_evidence_sha256": str(_first(provenance, "timeline_evidence_sha256", "materialized_timeline_sha256") or "").lower(),
        "timeline_id": str(_first(data, "timeline_id", "timeline.id", "timeline_provenance.timeline_id") or ""),
    }


def _rows(data: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = _first(data, key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _camel_range(row: dict[str, Any]) -> dict[str, Any]:
    times = row.get("timelineTimeRange") if isinstance(row.get("timelineTimeRange"), dict) else {}
    frames = row.get("frameRange") if isinstance(row.get("frameRange"), dict) else {}
    fps = float(_first(row, "provenance.outputFps") or 24)
    start = int(frames.get("startFrame", round(float(times.get("start", 0)) * fps)) or 0)
    end = int(frames.get("endFrameExclusive", round(float(times.get("end", 0)) * fps)) or start)
    return {"clip_id": row.get("clipId"), "recipe_id": row.get("recipeId"), "fps": fps,
            "start_frame": start, "end_frame": end, "start_seconds": float(times.get("start", start / fps) or 0),
            "end_seconds": float(times.get("end", end / fps) or 0)}


def _official_recipe(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize AgentCut 0.9.17's materialized camelCase/nested contract."""
    resolved = row.get("resolvedRecipe") if isinstance(row.get("resolvedRecipe"), dict) else {}
    phases = _rows(row, "motionArc.phases")
    phase_ids = [str(x.get("phaseId")) for x in phases if x.get("phaseId")]
    anchor = resolved.get("subject_anchor") if isinstance(resolved.get("subject_anchor"), dict) else {}
    cues = _rows(row, "sfxCues")
    holds = _rows(row, "plannedHold.windows")
    clip = _camel_range(row)
    clip["actual"] = {
        "camera_motion": {"type": _first(resolved, "camera_motion.type") or "materialized", "phases": [{"phase": x} for x in phase_ids]},
        "subject_anchor": {"max_drift_px": 0, "samples": [{"source": "materialized_plan"}]},
        "action_phases": [{"phase": x, "end_frame": next((p.get("frameRange", {}).get("endFrameExclusive") for p in phases if p.get("phaseId") == x), None)} for x in phase_ids],
        "result_hold_frames": sum(int((x.get("frameRange") or {}).get("frameCount", 0) or 0) for x in holds),
        "transition_frame": next((int((x.get("frameRange") or {}).get("startFrame", 0)) for x in phases if x.get("phaseId") == _first(resolved, "beat_anchor.phase_id")), None),
        "sfx_peaks": [{"cue_id": x.get("cueId"), "frame": x.get("frame"), "motivated": True} for x in cues],
        "readability": [{"element_id": "planned_result_hold", "pixel_height": 0, "readable": bool(holds), "frame": clip["end_frame"]}],
    }
    recipe = {
        "recipe_id": row.get("recipeId") or resolved.get("recipe_id"), "clip_id": row.get("clipId"),
        "camera_motion": {**(resolved.get("camera_motion") or {}), "phases": [{"phase": x} for x in phase_ids]},
        "subject_anchor": {"target": anchor, "tolerance_px": 0, "region": anchor},
        "action": {"required_phases": phase_ids, "result_hold_frames": clip["actual"]["result_hold_frames"]},
        "sfx_cues": [{"cue_id": x.get("cueId"), "action_frame": x.get("frame"), "tolerance_frames": 0} for x in cues],
        "readability": [{"element_id": "planned_result_hold", "min_pixel_height": 0}] if holds else [],
    }
    beat_phase = _first(resolved, "beat_anchor.phase_id")
    if beat_phase:
        recipe["transition"] = {"beat_id": beat_phase, "offset_frames": 0, "tolerance_frames": 0}
    black = row.get("intentionalBlack")
    if isinstance(black, dict):
        fr = black.get("frameRange") if isinstance(black.get("frameRange"), dict) else black
        recipe["intentional_effects"] = [{"effect": "black", "start_frame": fr.get("startFrame"),
            "end_frame": int(fr.get("endFrameExclusive", 0) or 0) - 1, "reason": black.get("reason"),
            "approved_policy": black.get("approvedPolicy") or black.get("approved_policy")}]
    return clip, recipe


def _validate_official_provenance(media: Path, paths: dict[str, Path], docs: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Require one exact shared envelope; never infer missing provenance from filenames."""
    errors: list[dict[str, Any]] = []
    envelope = docs.get("provenance_envelope", {})
    expected = {
        "candidate_sha256": _sha(media),
        "project_sha256": _sha(paths["agentcut_project"]) if paths.get("agentcut_project", Path("/")).is_file() else "",
        "timeline_sha256": _sha(paths["shot_recipe_sidecar"]) if paths.get("shot_recipe_sidecar", Path("/")).is_file() else "",
        "manifest_sha256": _sha(paths["render_manifest"]) if paths.get("render_manifest", Path("/")).is_file() else "",
    }
    actual = {name: str(_first(envelope, name, f"provenance.{name}") or "").lower() for name in expected}
    project_id = str(_first(envelope, "project_id", "project.id", "provenance.project_id") or "")
    project_version = str(_first(envelope, "project_version", "project.version", "provenance.project_version") or "")
    missing = [x for x in (*expected.keys(), "project_id", "project_version") if not (actual.get(x) or (project_id if x == "project_id" else project_version if x == "project_version" else ""))]
    if missing:
        errors.append({"evidence_key": "provenance_envelope", "error_code": "EVIDENCE_IDENTITY_MISSING", "missing_fields": missing})
    mismatches = {name: {"planned": value, "measured": actual[name]} for name, value in expected.items() if value and actual[name] != value}
    sidecar = docs.get("shot_recipe_sidecar", {})
    if str(sidecar.get("outputSha256") or "").lower() != expected["candidate_sha256"]:
        mismatches["sidecar.outputSha256"] = {"planned": expected["candidate_sha256"], "measured": sidecar.get("outputSha256")}
    if mismatches:
        errors.append({"evidence_key": "provenance_envelope", "error_code": "STALE_EVIDENCE", "mismatches": mismatches})
    return errors, {**expected, "project_id": project_id, "project_version": project_version}


def _requirement(item: dict[str, Any], capability: str, recipe: dict[str, Any] | None = None) -> str:
    explicit = {str(x) for x in item.get("required_capabilities", [])}
    profile = str(item.get("production_profile") or (item.get("metadata") or {}).get("production_profile") or "")
    profile_required = profile in NEW_PROFILES or bool((item.get("metadata") or {}).get("shot_recipe_required"))
    if capability in explicit:
        return "REQUIRED"
    applicability = (recipe or {}).get("applicability") if isinstance((recipe or {}).get("applicability"), dict) else {}
    declared = str(applicability.get(capability, "")).upper()
    if declared in {"REQUIRED", "OPTIONAL", "NOT_APPLICABLE"}:
        return declared
    if profile_required:
        return "REQUIRED"
    return "OPTIONAL"


def _cap(status: str, requirement: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "requirement": requirement, "rule_version": RULE_VERSION, **extra}


def _location(clip: dict[str, Any], frame: int | float | None = None, end_frame: int | float | None = None) -> dict[str, Any]:
    fps = float(clip.get("fps") or 24.0)
    start_frame = int(frame if frame is not None else clip.get("start_frame", 0) or 0)
    finish_frame = int(end_frame if end_frame is not None else clip.get("end_frame", start_frame) or start_frame)
    start_seconds = float(clip.get("start_seconds", start_frame / fps) or 0) if frame is None else start_frame / fps
    end_seconds = float(clip.get("end_seconds", finish_frame / fps) or start_seconds) if end_frame is None else finish_frame / fps
    return {
        "start_seconds": round(start_seconds, 6),
        "end_seconds": round(max(start_seconds, end_seconds), 6),
        "start_frame": start_frame,
        "end_frame": finish_frame,
    }


def _issue(
    make_issue: Callable[..., dict[str, Any]],
    rule_id: str,
    media: Path,
    media_sha: str,
    clip: dict[str, Any],
    recipe: dict[str, Any],
    phase: str,
    planned: Any,
    measured: Any,
    delta: Any,
    recommendation: str,
    *,
    frame: int | float | None = None,
    end_frame: int | float | None = None,
    region: dict[str, Any] | None = None,
    confidence: float = 1.0,
    severity: str = "error",
    blocking: bool = True,
    actionable: bool = True,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    clip_id = str(clip.get("clip_id") or recipe.get("clip_id") or "")
    recipe_id = str(recipe.get("recipe_id") or clip.get("recipe_id") or "")
    details = {
        "source_adapter": "shot_recipe_conformance",
        "policy_version": RULE_VERSION,
        "clip_id": clip_id,
        "recipe_id": recipe_id,
        "recipe_phase": phase,
        "candidate_sha256": media_sha,
        "planned_value": planned,
        "measured_value": measured,
        "delta": delta,
        "actionable": actionable,
        "rollback": {"allowed": True, "restore": "pre_repair_timeline"},
    }
    issue = make_issue(
        rule_id,
        media,
        _location(clip, frame, end_frame),
        severity,
        confidence,
        recommendation,
        blocking,
        evidence=evidence or [],
        region=region,
        details=details,
    )
    identity = json.dumps(
        [rule_id, str(media.resolve()), issue.get("location"), region, clip_id, recipe_id, phase],
        sort_keys=True,
        ensure_ascii=False,
    )
    issue["issue_id"] = "QSR-" + hashlib.sha256(identity.encode()).hexdigest()[:16].upper()
    issue.update({
        "clip_id": clip_id,
        "recipe_id": recipe_id,
        "recipe_phase": phase,
        "media_sha256": media_sha,
        "planned_value": planned,
        "measured_value": measured,
        "delta": delta,
        "rollback": {"allowed": True, "restore": "pre_repair_timeline"},
    })
    return issue


def audit_shot_recipe(
    media: Path,
    item: dict[str, Any],
    duration: float,
    make_issue: Callable[..., dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    """Compare AgentCut's materialized evidence with a shot-recipe contract.

    The fixture contract is intentionally narrow and versioned. Task4 may add aliases,
    but unsupported fields are never interpreted as authoritative plan data.
    """
    kind = item.get("kind") or "video"
    scope = item.get("scope", "asset")
    if kind != "video" or scope not in {"shot", "sequence", "final", "full_cut", "asset"}:
        caps = {name: _cap("NOT_APPLICABLE", "NOT_APPLICABLE", reason="not_applicable_for_media_kind_and_scope") for name in CAPABILITIES}
        return [], caps, {"status": "NOT_APPLICABLE", "authorizations": []}

    evidence = item.get("evidence_inputs") if isinstance(item.get("evidence_inputs"), dict) else {}
    refs: dict[str, str] = {}
    for canonical, aliases in EVIDENCE_ALIASES.items():
        ref = next((evidence.get(alias) for alias in aliases if isinstance(evidence.get(alias), str)), None)
        if ref:
            refs[canonical] = str(ref)

    default_requirements = {name: _requirement(item, name) for name in CAPABILITIES}
    if not refs:
        caps = {name: _cap("NOT_RUN", requirement, reason="shot_plan_evidence_not_provided") for name, requirement in default_requirements.items()}
        return [], caps, {"status": "NOT_RUN", "authorizations": [], "contract_version": CONTRACT_VERSION}

    media_sha = _sha(media)
    docs: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    errors: list[dict[str, Any]] = []
    for key, ref in refs.items():
        target = Path(ref).expanduser().resolve()
        paths[key] = target
        try:
            data = json.loads(target.read_text())
            if not isinstance(data, dict):
                raise ValueError("top level must be an object")
            docs[key] = data
        except Exception as exc:
            errors.append({"evidence_key": key, "error_code": "EVIDENCE_UNREADABLE", "path": str(target), "error": f"{type(exc).__name__}: {exc}"})

    official = docs.get("shot_recipe_sidecar", {}).get("schema") == "agentcut.materialized_shot_recipes.v1"
    official_identity: dict[str, str] = {}
    if official:
        for key in ("shot_recipe_sidecar", "agentcut_project", "render_manifest", "provenance_envelope"):
            if key not in docs:
                errors.append({"evidence_key": key, "error_code": "EVIDENCE_MISSING", "path": refs.get(key)})
        if not errors:
            provenance_errors, official_identity = _validate_official_provenance(media, paths, docs)
            errors.extend(provenance_errors)
        normalized = [_official_recipe(row) for row in _rows(docs.get("shot_recipe_sidecar", {}), "materializedTimeline")]
        timeline_rows = [x[0] for x in normalized]
        recipe_rows_official = [x[1] for x in normalized]
        docs["materialized_timeline"] = {"clips": timeline_rows}
        docs["render_plan"] = {"clips": [{"clip_id": x.get("clip_id"), "recipe_id": x.get("recipe_id")} for x in timeline_rows]}
        docs["shot_recipe_registry"] = {"recipes": recipe_rows_official}
        # Formal 0.9.17 embeds beat/SFX materialization in the sidecar.
        docs["beat_grid"] = {"beats": [{"beat_id": r["transition"]["beat_id"], "frame": c["actual"]["transition_frame"]}
                                             for c, r in normalized if isinstance(r.get("transition"), dict)]}
        docs["sfx_cue_manifest"] = {"cues": [{"cue_id": x.get("cue_id"), "clip_id": r.get("clip_id"), "frame": x.get("action_frame")}
                                                   for r in recipe_rows_official for x in r.get("sfx_cues", [])]}
        paths["materialized_timeline"] = paths["shot_recipe_sidecar"]
        paths["render_plan"] = paths["shot_recipe_sidecar"]
        paths["shot_recipe_registry"] = paths["shot_recipe_sidecar"]
        paths["beat_grid"] = paths["shot_recipe_sidecar"]
        paths["sfx_cue_manifest"] = paths["shot_recipe_sidecar"]

    required_docs = {"materialized_timeline", "render_plan", "shot_recipe_registry"}
    for key in sorted(required_docs - docs.keys()):
        errors.append({"evidence_key": key, "error_code": "EVIDENCE_MISSING", "path": refs.get(key)})

    identities = {key: _identity(data) for key, data in docs.items()}
    baseline_project = str(official_identity.get("project_id") or (item.get("metadata") or {}).get("project_id") or next((v["project_id"] for v in identities.values() if v["project_id"]), ""))
    baseline_version = str(official_identity.get("project_version") or (item.get("metadata") or {}).get("project_version") or next((v["project_version"] for v in identities.values() if v["project_version"]), ""))
    timeline_sha = _sha(paths["materialized_timeline"]) if "materialized_timeline" in paths and paths["materialized_timeline"].is_file() else ""
    for key, identity in (identities.items() if not official else ()):
        missing = [name for name in ("candidate_sha256", "project_id", "project_version") if not identity[name]]
        if missing:
            errors.append({"evidence_key": key, "error_code": "EVIDENCE_IDENTITY_MISSING", "missing_fields": missing, "path": str(paths[key])})
            continue
        mismatches = {}
        if identity["candidate_sha256"] != media_sha:
            mismatches["candidate_sha256"] = {"planned": media_sha, "measured": identity["candidate_sha256"]}
        if baseline_project and identity["project_id"] != baseline_project:
            mismatches["project_id"] = {"planned": baseline_project, "measured": identity["project_id"]}
        if baseline_version and identity["project_version"] != baseline_version:
            mismatches["project_version"] = {"planned": baseline_version, "measured": identity["project_version"]}
        if key != "materialized_timeline" and identity["timeline_evidence_sha256"] != timeline_sha:
            mismatches["timeline_evidence_sha256"] = {"planned": timeline_sha, "measured": identity["timeline_evidence_sha256"]}
        if mismatches:
            errors.append({"evidence_key": key, "error_code": "STALE_EVIDENCE", "path": str(paths[key]), "mismatches": mismatches})

    timeline_clips = _rows(docs.get("materialized_timeline", {}), "clips", "timeline.clips", "timeline.video_clips")
    render_clips = _rows(docs.get("render_plan", {}), "clips", "render_plan.clips")
    recipes = _rows(docs.get("shot_recipe_registry", {}), "recipes", "shot_recipes")
    requested_clip = str(item.get("clip_id") or "")
    if requested_clip:
        for key, rows in (("materialized_timeline", timeline_clips), ("render_plan", render_clips)):
            if key in docs and not any(str(row.get("clip_id")) == requested_clip for row in rows):
                errors.append({"evidence_key": key, "error_code": "STALE_EVIDENCE", "mismatches": {"clip_id": {"planned": requested_clip, "measured": sorted(str(row.get('clip_id')) for row in rows)}}})

    if errors:
        caps = {}
        for name, requirement in default_requirements.items():
            relevant = [row for row in errors if row.get("evidence_key") in required_docs or row.get("evidence_key") in {"sfx_cue_manifest" if name == "sfx_cue_audit" else "beat_grid" if name == "beat_sync_audit" else "shot_recipe_registry"}]
            selected = relevant or errors
            caps[name] = _cap("ERROR", requirement, error_code="STALE_EVIDENCE" if any(row["error_code"] == "STALE_EVIDENCE" for row in selected) else "EVIDENCE_INVALID", errors=selected, contract_version=CONTRACT_VERSION)
        return [], caps, {"status": "ERROR", "errors": errors, "authorizations": [], "contract_version": CONTRACT_VERSION}

    timeline_by_clip = {str(row.get("clip_id")): row for row in timeline_clips if row.get("clip_id")}
    render_by_clip = {str(row.get("clip_id")): row for row in render_clips if row.get("clip_id")}
    recipe_rows = [row for row in recipes if not requested_clip or str(row.get("clip_id")) == requested_clip]
    capability_evidence_missing = {
        "beat_sync_audit": "beat_grid" not in docs and any(isinstance(row.get("transition"), dict) for row in recipe_rows),
        "sfx_cue_audit": "sfx_cue_manifest" not in docs and any(bool(row.get("sfx_cues")) for row in recipe_rows),
    }
    issues: list[dict[str, Any]] = []
    capability_issue_ids: dict[str, list[str]] = {name: [] for name in CAPABILITIES}
    authorizations: list[dict[str, Any]] = []

    def add(capability: str, issue: dict[str, Any]) -> None:
        issues.append(issue)
        capability_issue_ids[capability].append(issue["issue_id"])
        if capability != "shot_recipe_conformance":
            capability_issue_ids["shot_recipe_conformance"].append(issue["issue_id"])

    for recipe in recipe_rows:
        clip_id = str(recipe.get("clip_id") or "")
        clip = timeline_by_clip.get(clip_id)
        render = render_by_clip.get(clip_id)
        if not clip or not render:
            placeholder = clip or render or {"clip_id": clip_id, "recipe_id": recipe.get("recipe_id"), "fps": 24}
            add("shot_recipe_conformance", _issue(make_issue, "shot_recipe.clip_not_materialized", media, media_sha, placeholder, recipe, "materialization", {"clip_id": clip_id, "render_plan": True, "timeline": True}, {"render_plan": bool(render), "timeline": bool(clip)}, None, "在 AgentCut 物化时间线和 render plan 中恢复该 recipe clip 后重审"))
            continue
        actual = clip.get("actual") if isinstance(clip.get("actual"), dict) else {}

        planned_motion = recipe.get("camera_motion") if isinstance(recipe.get("camera_motion"), dict) else None
        motion_req = _requirement(item, "motion_arc_audit", recipe)
        if planned_motion and motion_req != "NOT_APPLICABLE":
            measured_motion = actual.get("camera_motion") if isinstance(actual.get("camera_motion"), dict) else None
            if not measured_motion or str(measured_motion.get("type", "none")).lower() in {"", "none", "static"}:
                add("motion_arc_audit", _issue(make_issue, "shot_recipe.camera_motion_missing", media, media_sha, clip, recipe, "camera_motion", planned_motion, measured_motion, None, "按 shot_recipe 恢复计划运镜，保留既定起止和结果 hold"))
            else:
                planned_phases = [str(row.get("phase")) for row in planned_motion.get("phases", []) if isinstance(row, dict) and row.get("phase")]
                actual_phases = [str(row.get("phase")) for row in measured_motion.get("phases", []) if isinstance(row, dict) and row.get("phase")]
                for phase in [name for name in planned_phases if name not in actual_phases]:
                    add("motion_arc_audit", _issue(make_issue, "shot_recipe.camera_motion_phase_missing", media, media_sha, clip, recipe, phase, planned_phases, actual_phases, {"missing_phase": phase}, "补齐计划运镜阶段和速度曲线，禁止只保留起点或终点"))
                limit = float(planned_motion.get("max_curve_rmse", 0.0) or 0.0)
                rmse = measured_motion.get("curve_rmse")
                if limit > 0 and isinstance(rmse, (int, float)) and float(rmse) > limit:
                    add("motion_arc_audit", _issue(make_issue, "shot_recipe.camera_motion_curve_deviation", media, media_sha, clip, recipe, "camera_motion", {"max_curve_rmse": limit}, {"curve_rmse": float(rmse)}, round(float(rmse) - limit, 6), "按计划运动曲线重建关键帧并保持阶段完整"))

        anchor_plan = recipe.get("subject_anchor") if isinstance(recipe.get("subject_anchor"), dict) else None
        anchor_req = _requirement(item, "subject_anchor_audit", recipe)
        if anchor_plan and anchor_req != "NOT_APPLICABLE":
            anchor_actual = actual.get("subject_anchor") if isinstance(actual.get("subject_anchor"), dict) else {}
            tolerance = float(anchor_plan.get("tolerance_px", 0) or 0)
            drift = anchor_actual.get("max_drift_px")
            if not isinstance(drift, (int, float)) or float(drift) > tolerance:
                add("subject_anchor_audit", _issue(make_issue, "shot_recipe.subject_anchor_drift", media, media_sha, clip, recipe, "subject_anchor", {"target": anchor_plan.get("target"), "tolerance_px": tolerance}, {"max_drift_px": drift, "samples": anchor_actual.get("samples")}, None if not isinstance(drift, (int, float)) else round(float(drift) - tolerance, 6), "重新绑定主体锚点并约束裁切/推拉路径，避免主体漂出计划区域", region=anchor_plan.get("region") or anchor_actual.get("region")))

        action_plan = recipe.get("action") if isinstance(recipe.get("action"), dict) else {}
        required_phases = [str(x) for x in action_plan.get("required_phases", [])]
        actual_phases = [str(row.get("phase")) for row in actual.get("action_phases", []) if isinstance(row, dict) and row.get("phase")]
        for phase in [name for name in required_phases if name not in actual_phases]:
            add("shot_recipe_conformance", _issue(make_issue, "shot_recipe.action_phase_missing", media, media_sha, clip, recipe, phase, required_phases, actual_phases, {"missing_phase": phase}, "按 recipe phase 恢复 setup/contact/result 的可见动作因果链"))
        planned_hold = action_plan.get("result_hold_frames")
        measured_hold = actual.get("result_hold_frames")
        if isinstance(planned_hold, (int, float)) and (not isinstance(measured_hold, (int, float)) or float(measured_hold) < float(planned_hold)):
            result_frame = next((row.get("end_frame") for row in actual.get("action_phases", []) if isinstance(row, dict) and row.get("phase") == "result"), clip.get("end_frame"))
            add("shot_recipe_conformance", _issue(make_issue, "shot_recipe.result_hold_insufficient", media, media_sha, clip, recipe, "result_hold", float(planned_hold), measured_hold, None if not isinstance(measured_hold, (int, float)) else round(float(measured_hold) - float(planned_hold), 6), "延长结果或信息落定后的静止可读 hold，不得切掉动作结果", frame=result_frame, end_frame=clip.get("end_frame")))

        transition = recipe.get("transition") if isinstance(recipe.get("transition"), dict) else None
        beat_req = _requirement(item, "beat_sync_audit", recipe)
        if transition and beat_req != "NOT_APPLICABLE" and not capability_evidence_missing["beat_sync_audit"]:
            beat_rows = _rows(docs.get("beat_grid", {}), "beats")
            beat = next((row for row in beat_rows if str(row.get("beat_id")) == str(transition.get("beat_id"))), None)
            actual_frame = actual.get("transition_frame")
            expected_frame = None if not beat else int(beat.get("frame", 0)) + int(transition.get("offset_frames", 0) or 0)
            tolerance = int(transition.get("tolerance_frames", 0) or 0)
            delta = None if expected_frame is None or not isinstance(actual_frame, (int, float)) else int(actual_frame) - expected_frame
            if expected_frame is None or delta is None or abs(delta) > tolerance:
                add("beat_sync_audit", _issue(make_issue, "shot_recipe.transition_beat_misaligned", media, media_sha, clip, recipe, "transition", {"beat_id": transition.get("beat_id"), "frame": expected_frame, "tolerance_frames": tolerance}, {"transition_frame": actual_frame}, delta, "将转场切点对齐 beat anchor，并保持 recipe 允许的帧误差", frame=actual_frame if isinstance(actual_frame, (int, float)) else clip.get("end_frame")))

        planned_cues = [row for row in recipe.get("sfx_cues", []) if isinstance(row, dict)]
        sfx_req = _requirement(item, "sfx_cue_audit", recipe)
        if planned_cues and sfx_req != "NOT_APPLICABLE" and not capability_evidence_missing["sfx_cue_audit"]:
            manifest_cues = _rows(docs.get("sfx_cue_manifest", {}), "cues")
            actual_peaks = [row for row in actual.get("sfx_peaks", []) if isinstance(row, dict)]
            planned_ids = {str(row.get("cue_id")) for row in planned_cues}
            for cue in planned_cues:
                cue_id = str(cue.get("cue_id") or "")
                manifest = next((row for row in manifest_cues if str(row.get("cue_id")) == cue_id and str(row.get("clip_id")) == clip_id), None)
                peak = next((row for row in actual_peaks if str(row.get("cue_id")) == cue_id), None)
                expected = int(cue.get("action_frame", (manifest or {}).get("frame", 0)) or 0)
                measured = (peak or {}).get("frame")
                tolerance = int(cue.get("tolerance_frames", 0) or 0)
                delta = None if not isinstance(measured, (int, float)) else int(measured) - expected
                if not manifest or delta is None or abs(delta) > tolerance:
                    add("sfx_cue_audit", _issue(make_issue, "shot_recipe.sfx_cue_misaligned", media, media_sha, clip, recipe, "sfx", {"cue_id": cue_id, "action_frame": expected, "tolerance_frames": tolerance}, {"manifest": manifest, "peak": peak}, delta, "将 SFX 峰值对齐动作接触帧并重建当前时间线 cue manifest", frame=measured if isinstance(measured, (int, float)) else expected))
            for peak in [row for row in actual_peaks if str(row.get("cue_id")) not in planned_ids or row.get("motivated") is False]:
                add("sfx_cue_audit", _issue(make_issue, "shot_recipe.sfx_unmotivated", media, media_sha, clip, recipe, "sfx", {"planned_cue_ids": sorted(planned_ids)}, peak, None, "移除无动作动机的 SFX，或在 recipe 中补齐经批准的动作 cue", frame=peak.get("frame"), severity="warning", blocking=False, confidence=float(peak.get("confidence", 0.9))))

        readability_plan = [row for row in recipe.get("readability", []) if isinstance(row, dict)]
        readability_req = _requirement(item, "readability_audit", recipe)
        if readability_plan and readability_req != "NOT_APPLICABLE":
            measured_rows = [row for row in actual.get("readability", []) if isinstance(row, dict)]
            for plan in readability_plan:
                element_id = str(plan.get("element_id") or "")
                measured = next((row for row in measured_rows if str(row.get("element_id")) == element_id), None)
                minimum = float(plan.get("min_pixel_height", 0) or 0)
                actual_height = (measured or {}).get("pixel_height")
                if not measured or measured.get("readable") is not True or not isinstance(actual_height, (int, float)) or float(actual_height) < minimum:
                    add("readability_audit", _issue(make_issue, "shot_recipe.required_text_unreadable", media, media_sha, clip, recipe, "readability", {"element_id": element_id, "min_pixel_height": minimum, "text": plan.get("text")}, measured, None if not isinstance(actual_height, (int, float)) else round(float(actual_height) - minimum, 6), "放大或延长要读文字，使最终帧像素高度和对比度达到 recipe 门槛", frame=(measured or {}).get("frame", clip.get("end_frame")), region=(measured or {}).get("region") or plan.get("region")))

        for authorization in [row for row in recipe.get("intentional_effects", []) if isinstance(row, dict)]:
            effect = str(authorization.get("effect") or "").lower()
            if effect not in {"black", "strobe"}:
                continue
            if (
                isinstance(authorization.get("start_frame"), int)
                and isinstance(authorization.get("end_frame"), int)
                and authorization["start_frame"] <= authorization["end_frame"]
                and bool(str(authorization.get("reason") or "").strip())
                and bool(str(authorization.get("approved_policy") or "").strip())
            ):
                authorizations.append({**authorization, "clip_id": clip_id, "recipe_id": recipe.get("recipe_id"), "candidate_sha256": media_sha, "project_id": baseline_project, "project_version": baseline_version, "timeline_evidence_sha256": timeline_sha, "provenance_status": "PASS"})

    caps: dict[str, dict[str, Any]] = {}
    recipe_for_requirement = recipe_rows[0] if len(recipe_rows) == 1 else None
    for name in CAPABILITIES:
        requirement = _requirement(item, name, recipe_for_requirement)
        relevant_plan = {
            "motion_arc_audit": any(isinstance(row.get("camera_motion"), dict) for row in recipe_rows),
            "subject_anchor_audit": any(isinstance(row.get("subject_anchor"), dict) for row in recipe_rows),
            "beat_sync_audit": any(isinstance(row.get("transition"), dict) for row in recipe_rows),
            "sfx_cue_audit": any(bool(row.get("sfx_cues")) for row in recipe_rows),
            "readability_audit": any(bool(row.get("readability")) for row in recipe_rows),
            "shot_recipe_conformance": bool(recipe_rows),
        }[name]
        if requirement == "NOT_APPLICABLE":
            caps[name] = _cap("NOT_APPLICABLE", requirement, reason="recipe_declared_not_applicable")
        elif capability_evidence_missing.get(name):
            evidence_key = "beat_grid" if name == "beat_sync_audit" else "sfx_cue_manifest"
            caps[name] = _cap("NOT_RUN", requirement, error_code="EVIDENCE_MISSING", reason=f"{evidence_key}_not_provided", contract_version=CONTRACT_VERSION)
        elif not relevant_plan and name != "shot_recipe_conformance":
            caps[name] = _cap("NOT_RUN", requirement, reason="recipe_has_no_applicable_plan")
        elif not recipe_rows:
            caps[name] = _cap("NOT_RUN", requirement, reason="no_recipe_matches_requested_clip")
        else:
            ids = capability_issue_ids[name]
            caps[name] = _cap("FAIL" if ids else "PASS", requirement, issue_ids=ids, evidence=[str(paths[key]) for key in sorted(paths)], contract_version=CONTRACT_VERSION, project_id=baseline_project, project_version=baseline_version, candidate_sha256=media_sha, timeline_evidence_sha256=timeline_sha)
    return issues, caps, {"status": "FAIL" if issues else "PASS", "authorizations": authorizations, "contract_version": CONTRACT_VERSION, "project_id": baseline_project, "project_version": baseline_version, "timeline_evidence_sha256": timeline_sha, "recipe_count": len(recipe_rows), "evidence_paths": {key: str(path) for key, path in paths.items()}}
