from __future__ import annotations

import json
import hashlib
import math
import os
import re
import uuid
from array import array
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .compiler import CompiledCommand, compile_project
from .errors import AgentCutError, ValidationError
from .models import Project
from .runtime import resolve_binary
from .release_gate import validate_release_output
from .final_visual import FinalVisualPolicy, FinalVisualValidator
from .validation import MediaValidator, ValidationReport, validate_audio_safety, validate_cleanup_regions, validate_cut_reason_contract, validate_hold_slots, validate_narrative, validate_outro, validate_release_gate, validate_shot_recipes, validate_source_admission, validate_subtitles
from .shot_recipes import list_short_drama_recipes, map_shot_recipe_repairs
from .transform import TransformResult, load_json_value, rollback_project, transform_project, write_json_atomic, content_hash


@dataclass(frozen=True)
class RenderResult:
    output: str
    duration: float
    command: tuple[str, ...]
    audio_duration: float | None = None
    manifest: dict[str, Any] | None = None


@dataclass(frozen=True)
class RenderProgress:
    time: float
    duration: float
    progress: float


@dataclass(frozen=True)
class ProjectTransformResult:
    transformed: TransformResult
    valid: bool
    validation: ValidationReport | None
    dry_run: bool
    output: str | None = None
    audit_path: str | None = None

    def summary(self, include_project: bool = False, include_audit: bool = False) -> dict[str, Any]:
        result = {
            "valid": self.valid, "dryRun": self.dry_run, "output": self.output,
            "auditPath": self.audit_path, **self.transformed.summary(),
        }
        if self.validation is not None:
            result["validation"] = self.validation.to_dict()
        if include_project:
            result["project"] = self.transformed.project
        if include_audit:
            result["audit"] = self.transformed.audit
        return {k: v for k, v in result.items() if v is not None}


@dataclass(frozen=True)
class BatchItemResult:
    project: str
    ok: bool
    output: str | None = None
    duration: float | None = None
    audio_duration: float | None = None
    manifest: dict[str, Any] | None = None
    error: str | None = None


def _render_worker(project: str, ffmpeg: str, overwrite: bool) -> BatchItemResult:
    try:
        result = AgentCutEngine(ffmpeg).render(project, overwrite=overwrite)
        return BatchItemResult(project, True, result.output, result.duration, result.audio_duration, result.manifest)
    except Exception as exc:  # Worker boundary: serialize all task failures.
        return BatchItemResult(project, False, error=f"{type(exc).__name__}: {exc}")


class AgentCutEngine:
    def __init__(self, ffmpeg: str | None = "auto", ffprobe: str | None = "auto") -> None:
        self.ffmpeg = resolve_binary(ffmpeg)
        self.ffprobe = resolve_binary(ffprobe, "ffprobe")

    def load(self, source: str | Path | dict[str, Any]) -> Project:
        if isinstance(source, dict):
            return Project.parse(source)
        path = Path(source).resolve()
        with path.open(encoding="utf-8") as f:
            return Project.parse(json.load(f), base_dir=path.parent)

    def compile(self, source: str | Path | dict[str, Any], *, overwrite: bool = False) -> CompiledCommand:
        project = self.load(source)
        cut_reason_issues, _coverage = validate_cut_reason_contract(project)
        source_issues, _source_coverage = validate_source_admission(project)
        hold_issues, _hold_coverage = validate_hold_slots(project)
        recipe_issues, _recipe_coverage = validate_shot_recipes(project)
        errors = [issue for issue in (*cut_reason_issues, *source_issues, *hold_issues, *recipe_issues) if issue.severity == "error"]
        if errors:
            detail = "; ".join(f"{issue.code}: {issue.message}" for issue in errors[:10])
            raise ValidationError(f"compile preflight failed: {detail}")
        return compile_project(project, self.ffmpeg, overwrite)

    def validate(self, source: str | Path | dict[str, Any], *, strict_media: bool = False) -> ValidationReport:
        project = self.load(source)
        if strict_media:
            return MediaValidator(self.ffprobe).validate(project)
        issues, subtitle_coverage = validate_subtitles(project)
        narrative_issues, narrative_coverage = validate_narrative(project)
        issues.extend(narrative_issues)
        cut_reason_issues, cut_reason_coverage = validate_cut_reason_contract(project)
        issues.extend(cut_reason_issues)
        outro_issues, outro_coverage = validate_outro(project, self.ffmpeg)
        issues.extend(outro_issues)
        cleanup_issues, cleanup_coverage = validate_cleanup_regions(project)
        issues.extend(cleanup_issues)
        audio_issues, audio_coverage = validate_audio_safety(project, self.ffmpeg)
        issues.extend(audio_issues)
        source_issues, source_coverage = validate_source_admission(project)
        issues.extend(source_issues)
        release_issues, release_coverage = validate_release_gate(project, source_coverage)
        issues.extend(release_issues)
        hold_issues, hold_coverage = validate_hold_slots(project)
        issues.extend(hold_issues)
        recipe_issues, recipe_coverage = validate_shot_recipes(project)
        issues.extend(recipe_issues)
        return ValidationReport(
            not any(x.severity == "error" for x in issues), project.duration,
            len(project.video_tracks), len(project.audio_tracks), len(project.subtitle_tracks),
            tuple(issues), {}, {"subtitles": subtitle_coverage, "narrative": narrative_coverage, "cutReason": cut_reason_coverage, "outro": outro_coverage,
                               "cleanup": cleanup_coverage, "audioSafety": audio_coverage,
                               "sourceAdmission": source_coverage, "releaseGate": release_coverage,
                               "holdSlots": hold_coverage, "shotRecipes": recipe_coverage},
        )

    def list_shot_recipes(self) -> dict[str, Any]:
        return list_short_drama_recipes()

    def map_shot_recipe_repairs(self, source: str | Path | dict[str, Any], *,
                                aggregate_problems: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        project = self.load(source)
        tasks = map_shot_recipe_repairs(project, aggregate_problems=aggregate_problems)
        return {
            "schema": "agentcut.shot_recipe_repair_tasks.v1", "taskCount": len(tasks),
            "tasks": tasks, "platformMutationAuthorized": False,
        }

    def validate_release(self, final: str | Path, review: str | Path | dict[str, Any], *,
                         project: str | Path | dict[str, Any] | None = None) -> dict[str, Any]:
        conditional_count = 0
        unresolved_hold_count = 0
        source_admission_valid = True
        source_coverage: dict[str, Any] | None = None
        if project is not None:
            parsed = self.load(project)
            source_issues, source_coverage = validate_source_admission(parsed)
            source_admission_valid = not any(issue.severity == "error" for issue in source_issues)
            conditional_count = int(source_coverage.get("conditionalSourceCount") or 0)
            unresolved_hold_count = len(parsed.hold_slots)
        result = validate_release_output(final, review, conditional_source_count=conditional_count)
        if conditional_count and "RELEASE_CONDITIONAL_SOURCES_UNRESOLVED" not in result.get("failures", []):
            result = {
                **result, "status": "FAIL", "cleanRelease": False,
                "failures": [*result.get("failures", []), "RELEASE_CONDITIONAL_SOURCES_UNRESOLVED"],
                "nextAction": "replace_conditional_sources_and_rerun_full_qa",
            }
        if not source_admission_valid:
            result = {
                **result, "status": "FAIL", "cleanRelease": False,
                "failures": [*result.get("failures", []), "SOURCE_ADMISSION_NOT_CLEAN"],
                "nextAction": "hold_release",
            }
        if unresolved_hold_count:
            result = {
                **result, "status": "FAIL", "cleanRelease": False,
                "failures": [*result.get("failures", []), "RELEASE_UNRESOLVED_HOLD_SLOTS"],
                "unresolvedHoldCount": unresolved_hold_count,
                "nextAction": "replace_hold_slots_and_rerun_full_qa",
            }
        if source_coverage is not None:
            result["sourceAdmission"] = source_coverage
        return result

    def validate_final_visual(self, final: str | Path, *,
                              project: str | Path | dict[str, Any] | Project | None = None,
                              report: str | Path | None = None,
                              policy: dict[str, Any] | FinalVisualPolicy | None = None) -> dict[str, Any]:
        parsed: Project | None
        if isinstance(project, Project):
            parsed = project
        elif project is None:
            parsed = None
        else:
            parsed = self.load(project)
        if isinstance(policy, FinalVisualPolicy):
            actual_policy = policy
        elif policy is not None:
            actual_policy = FinalVisualPolicy.parse(policy)
        elif parsed is not None and (parsed.final_visual_policy.enabled or parsed.final_visual_policy.required):
            actual_policy = parsed.final_visual_policy
        else:
            actual_policy = FinalVisualPolicy(enabled=True, required=True)
        result = FinalVisualValidator(self.ffmpeg, self.ffprobe).analyze(
            final, project=parsed, policy=actual_policy,
        )
        if parsed is not None:
            _source_issues, source_coverage = validate_source_admission(parsed)
            release_blockers = []
            conditional_count = int(source_coverage.get("conditionalSourceCount") or 0)
            if conditional_count:
                release_blockers.append({
                    "code": "FINAL_VISUAL_CONDITIONAL_SOURCES_UNRESOLVED",
                    "message": "conditional sources are valid only for NON_RELEASE_ROUGH_ASSEMBLY",
                    "conditionalSourceCount": conditional_count,
                })
            if parsed.hold_slots:
                release_blockers.append({
                    "code": "FINAL_VISUAL_HOLD_SLOTS_UNRESOLVED",
                    "message": "explicit hold/placeholder slots must be replaced before final visual approval",
                    "holdSlots": [
                        {"id": slot.id, "start": slot.start, "end": slot.end,
                         "replacementCondition": slot.replacement_condition}
                        for slot in parsed.hold_slots
                    ],
                })
            if release_blockers:
                result["violations"] = [*result.get("violations", []), *release_blockers]
                result["releaseBlockers"] = release_blockers
                result["hardGatePassed"] = False
                result["status"] = "FAIL"
                result["platformMutationAuthorized"] = False
        destination = report or actual_policy.report_path
        if destination:
            result["reportPath"] = str(Path(destination).resolve())
            FinalVisualValidator.write_report(destination, result)
        return result

    def transform(self, source: str | Path | dict[str, Any], plan: str | Path | dict[str, Any], *,
                  dry_run: bool = True, output: str | Path | None = None,
                  audit_path: str | Path | None = None, strict_media: bool = False,
                  require_cut_reason: bool = False) -> ProjectTransformResult:
        project_value, project_path = load_json_value(source)
        plan_value, _ = load_json_value(plan)
        transformed = transform_project(project_value, plan_value, require_cut_reason=require_cut_reason)
        validation = None
        valid = True
        if strict_media:
            base_dir = project_path.parent if project_path else None
            parsed = Project.parse(transformed.project, base_dir=base_dir)
            validation = MediaValidator(self.ffprobe).validate(parsed)
            valid = validation.valid
        written_output = written_audit = None
        if not dry_run and valid:
            if output is None:
                raise ValidationError("output is required unless dryRun is true")
            destination = str(Path(output).resolve())
            actual_audit = audit_path or f"{destination}.audit.json"
            written_audit = write_json_atomic(actual_audit, transformed.audit)
            written_output = write_json_atomic(destination, transformed.project)
        return ProjectTransformResult(transformed, valid, validation, dry_run, written_output, written_audit)

    def rollback(self, audit: str | Path | dict[str, Any], *, output: str | Path | None = None,
                 dry_run: bool = False) -> dict[str, Any]:
        audit_value, _ = load_json_value(audit)
        project = rollback_project(audit_value)
        written_output = None
        if not dry_run:
            if output is None:
                raise ValidationError("output is required unless dryRun is true")
            written_output = write_json_atomic(output, project)
        return {"dryRun": dry_run, "output": written_output, "projectHash": content_hash(project), "project": project}

    def render(self, source: str | Path | dict[str, Any], *, overwrite: bool = False,
               on_progress: Callable[[RenderProgress], None] | None = None) -> RenderResult:
        project = self.load(source)
        subtitle_issues, _coverage = validate_subtitles(project)
        narrative_issues, _narrative_coverage = validate_narrative(project)
        cut_reason_issues, _cut_reason_coverage = validate_cut_reason_contract(project)
        outro_issues, _outro_coverage = validate_outro(project, self.ffmpeg)
        cleanup_issues, _cleanup_coverage = validate_cleanup_regions(project)
        audio_issues, _audio_coverage = validate_audio_safety(project, self.ffmpeg)
        source_issues, _source_coverage = validate_source_admission(project)
        hold_issues, _hold_coverage = validate_hold_slots(project)
        recipe_issues, _recipe_coverage = validate_shot_recipes(project)
        preflight_errors = [x for x in (*subtitle_issues, *narrative_issues, *cut_reason_issues, *outro_issues, *cleanup_issues, *audio_issues, *source_issues, *hold_issues, *recipe_issues) if x.severity == "error"]
        if preflight_errors:
            detail = "; ".join(f"{x.code}: {x.message}" for x in preflight_errors[:10])
            raise ValidationError(f"render preflight failed: {detail}")
        if shutil.which(self.ffmpeg) is None:
            raise AgentCutError(f"FFmpeg executable not found: {self.ffmpeg}")
        output = Path(project.output.path)
        if not output.is_absolute() and not isinstance(source, dict):
            output = Path(source).resolve().parent / output
        output.parent.mkdir(parents=True, exist_ok=True)
        has_audio = any(track.enabled and track.clips for track in project.audio_tracks) or project.outro.enabled
        policy = project.master_audio_policy
        two_pass = bool(has_audio and policy and policy.loudness_target_lufs is not None)
        if output.exists() and not overwrite:
            raise AgentCutError(f"output already exists (use overwrite): {output}")
        token = uuid.uuid4().hex
        candidate = output.parent / f".{output.stem}.{token}.agentcut-candidate{output.suffix or '.mp4'}"
        premaster = output.parent / f".{output.stem}.{token}.agentcut-premaster.mkv"
        failure_report = Path(str(output) + ".failed-audio-qa.json")
        visual_failure_report = Path(str(output) + ".failed-visual-qa.json")
        temporary_paths = [candidate, premaster]
        loudnorm_measurement: dict[str, float] | None = None
        mastering_filter: str | None = None
        final_visual_report: dict[str, Any] | None = None
        render_argv: list[str] = []
        projected_peak = (_audio_coverage.get("projected") or {}).get("worstCombinedPeakDbfs")
        premaster_attenuation_db = min(0.0, -6.0 - float(projected_peak)) if projected_peak is not None else -24.0

        def run_ffmpeg(argv: list[str], *, progress: bool, label: str) -> None:
            actual = argv
            if progress:
                actual = [*argv[:-1], "-progress", "pipe:2", "-nostats", argv[-1]]
            process = subprocess.Popen(actual, stderr=subprocess.PIPE, text=True)
            assert process.stderr is not None
            tail: list[str] = []
            for line in process.stderr:
                tail.append(line.rstrip())
                tail = tail[-30:]
                if progress and on_progress and line.startswith("out_time_us="):
                    try:
                        rendered_time = max(0.0, float(line.split("=", 1)[1]) / 1_000_000)
                        on_progress(RenderProgress(rendered_time, project.duration, min(1.0, rendered_time / project.duration)))
                    except ValueError:
                        pass
            return_code = process.wait()
            process.stderr.close()
            if return_code != 0:
                raise AgentCutError(f"FFmpeg {label} failed:\n" + "\n".join(tail))

        def remove_option(argv: list[str], option: str) -> list[str]:
            result = list(argv)
            while option in result:
                index = result.index(option)
                del result[index:index + 2]
            return result

        try:
            if two_pass:
                command = compile_project(
                    project, self.ffmpeg, True, master_audio_mode="premaster",
                    premaster_attenuation_db=premaster_attenuation_db,
                )
                premaster_argv = [*command.argv[:-1], str(premaster)]
                audio_codec_index = premaster_argv.index("-c:a")
                premaster_argv[audio_codec_index + 1] = "pcm_s24le"
                premaster_argv = remove_option(premaster_argv, "-b:a")
                run_ffmpeg(premaster_argv, progress=on_progress is not None, label="premaster render")

                processing_ceiling = policy.true_peak_ceiling_dbtp - policy.codec_headroom_db
                measurement_filter = (
                    f"loudnorm=I={policy.loudness_target_lufs:g}:TP={processing_ceiling:g}:"
                    f"LRA={policy.loudness_range_lu:g}:print_format=json"
                )
                measured = subprocess.run([
                    self.ffmpeg, "-hide_banner", "-nostats", "-i", str(premaster), "-map", "0:a:0",
                    "-af", measurement_filter, "-f", "null", "-",
                ], capture_output=True, text=True)
                blocks = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', measured.stderr, re.DOTALL)
                if measured.returncode != 0 or not blocks:
                    raise AgentCutError("FFmpeg loudnorm measurement failed:\n" + "\n".join(measured.stderr.splitlines()[-30:]))
                raw_measurement = json.loads(blocks[-1])
                field_map = {
                    "inputI": "input_i", "inputTp": "input_tp", "inputLra": "input_lra",
                    "inputThresh": "input_thresh", "targetOffset": "target_offset",
                }
                loudnorm_measurement = {}
                for output_name, input_name in field_map.items():
                    try:
                        value = float(raw_measurement[input_name])
                    except (KeyError, TypeError, ValueError) as exc:
                        raise AgentCutError(f"invalid loudnorm measurement field {input_name}") from exc
                    if not math.isfinite(value):
                        raise AgentCutError(f"non-finite loudnorm measurement field {input_name}: {value!r}")
                    loudnorm_measurement[output_name] = value
                mastering_filter = (
                    f"loudnorm=I={policy.loudness_target_lufs:g}:TP={processing_ceiling:g}:LRA={policy.loudness_range_lu:g}:"
                    f"measured_I={loudnorm_measurement['inputI']:g}:measured_TP={loudnorm_measurement['inputTp']:g}:"
                    f"measured_LRA={loudnorm_measurement['inputLra']:g}:measured_thresh={loudnorm_measurement['inputThresh']:g}:"
                    f"offset={loudnorm_measurement['targetOffset']:g}:linear=true:print_format=summary"
                )
                render_argv = [
                    self.ffmpeg, "-hide_banner", "-y", "-i", str(premaster),
                    "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", mastering_filter,
                    "-c:a", project.output.audio_codec, "-b:a", project.output.audio_bitrate,
                    "-t", f"{project.duration:g}", str(candidate),
                ]
                run_ffmpeg(render_argv, progress=False, label="measured loudnorm second pass")
            else:
                command = compile_project(project, self.ffmpeg, True)
                render_argv = [*command.argv[:-1], str(candidate)]
                run_ffmpeg(render_argv, progress=on_progress is not None, label="render")

            video_probe = subprocess.run([
                self.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration", "-of", "json", str(candidate),
            ], capture_output=True, text=True)
            try:
                video_duration = float(json.loads(video_probe.stdout)["streams"][0]["duration"])
            except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                video_duration = float("inf")
            if abs(video_duration - project.duration) > 0.1:
                raise AgentCutError(f"rendered video duration gate failed: video={video_duration!r}s, project={project.duration:g}s; staged output removed")

            visual_policy = project.final_visual_policy
            if visual_policy.enabled or visual_policy.required:
                final_visual_report = FinalVisualValidator(self.ffmpeg, self.ffprobe).analyze(
                    candidate, project=project, policy=visual_policy, reported_media_path=output,
                )
                visual_report_path = visual_policy.report_path or str(output) + ".final-visual-qa.json"
                if not final_visual_report["hardGatePassed"]:
                    visual_report_path = visual_policy.report_path or str(visual_failure_report)
                final_visual_report["reportPath"] = str(Path(visual_report_path).resolve())
                FinalVisualValidator.write_report(visual_report_path, final_visual_report)
                if not final_visual_report["hardGatePassed"]:
                    raise AgentCutError(
                        "final visual hard gate failed: " +
                        ", ".join(item["code"] for item in final_visual_report["violations"][:10]) +
                        f"; staged output removed; report={visual_report_path}"
                    )

            audio_duration = None
            audio_metrics = None
            if has_audio:
                probe = subprocess.run([
                    self.ffprobe, "-v", "error", "-select_streams", "a:0",
                    "-show_entries", "stream=start_time,duration", "-of", "json", str(candidate),
                ], capture_output=True, text=True)
                try:
                    streams = json.loads(probe.stdout).get("streams", []) if probe.returncode == 0 else []
                    audio_duration = float(streams[0]["duration"])
                    audio_start = float(streams[0].get("start_time", 0))
                except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                    audio_start = float("inf")
                drift = abs(audio_duration - project.duration) if audio_duration is not None else float("inf")
                if drift > 0.1 or abs(audio_start) > 0.1:
                    raise AgentCutError(
                        f"rendered audio duration gate failed: audio={audio_duration!r}s, "
                        f"project={project.duration:g}s, drift={drift:g}s, start={audio_start!r}s; staged output removed"
                    )
                measured = subprocess.run([
                    self.ffmpeg, "-hide_banner", "-i", str(candidate), "-filter_complex", "ebur128=peak=true", "-f", "null", "-",
                ], capture_output=True, text=True)
                integrated_matches = re.findall(r"I:\s*(-?[0-9.]+) LUFS", measured.stderr)
                peak_matches = re.findall(r"Peak:\s*(-?[0-9.]+) dBFS", measured.stderr)
                integrated = float(integrated_matches[-1]) if integrated_matches else None
                true_peak = float(peak_matches[-1]) if peak_matches else None
                decoder = subprocess.Popen([
                    self.ffmpeg, "-v", "error", "-i", str(candidate), "-map", "0:a:0", "-f", "s16le", "-acodec", "pcm_s16le", "-",
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                clipped_samples = total_samples = 0
                assert decoder.stdout is not None
                remainder = b""
                for chunk in iter(lambda: decoder.stdout.read(1024 * 1024), b""):
                    chunk = remainder + chunk
                    if len(chunk) % 2:
                        remainder = chunk[-1:]
                        chunk = chunk[:-1]
                    else:
                        remainder = b""
                    samples = array("h")
                    samples.frombytes(chunk)
                    total_samples += len(samples)
                    clipped_samples += sum(1 for sample in samples if sample in {-32768, 32767})
                decoder.wait()
                decoder.stdout.close()
                if decoder.stderr is not None:
                    decoder.stderr.close()
                audio_metrics = {"integratedLoudnessLufs": integrated, "truePeakDbtp": true_peak,
                                 "clippedSampleCount": clipped_samples, "decodedSampleCount": total_samples}
                audio_failures = []
                if project.requires_master_audio_safety or (policy and policy.required):
                    if policy is None:
                        audio_failures.append("master audio policy missing")
                    else:
                        if true_peak is None or true_peak > policy.true_peak_ceiling_dbtp + 1e-6:
                            audio_failures.append(f"true peak {true_peak!r} exceeds {policy.true_peak_ceiling_dbtp:g} dBTP")
                        if clipped_samples > policy.max_clipped_samples:
                            audio_failures.append(f"clipped samples {clipped_samples} exceeds {policy.max_clipped_samples}")
                        if policy.loudness_target_lufs is not None and (integrated is None or abs(integrated - policy.loudness_target_lufs) > 1.0):
                            audio_failures.append(f"integrated loudness {integrated!r} differs from target {policy.loudness_target_lufs:g} LUFS")
                if audio_failures:
                    write_json_atomic(failure_report, {
                        "outputPublished": False, "stagedOutputRemoved": True,
                        "existingOutputPreserved": output.exists(), "policy": asdict(policy) if policy else None,
                        "mastering": {"mode": "measured-two-pass" if two_pass else "single-pass",
                                      "measurement": loudnorm_measurement,
                                      "premasterAttenuationDb": premaster_attenuation_db if two_pass else 0.0},
                        "metrics": audio_metrics, "failures": audio_failures,
                    })
                    raise AgentCutError("master audio safety gate failed: " + "; ".join(audio_failures) + f"; report={failure_report}")
            def digest(path: str) -> str:
                value = hashlib.sha256()
                with open(path, "rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        value.update(chunk)
                return value.hexdigest()

            outro = project.outro
            outro_manifest: dict[str, Any] = {"present": False}
            if outro.enabled:
                assets = [{"kind": "template", "path": outro.asset_path, "sha256": digest(outro.asset_path)}]
                for kind, path in (("audio", outro.audio_path), ("sfx", outro.sfx_path)):
                    if path:
                        assets.append({"kind": kind, "path": path, "sha256": digest(path)})
                outro_manifest = {"present": True, "brand": outro.brand, "template": outro.template, "templateVersion": outro.template_version,
                                  "actualStart": project.main_duration, "actualEnd": project.duration, "duration": outro.duration,
                                  "endsAtTimelineEnd": True, "fit": outro.fit, "audioPolicy": outro.audio_policy,
                                  "includeInTotalDuration": outro.include_in_total_duration,
                                  "accountedDuration": project.duration if outro.include_in_total_duration else project.main_duration,
                                  "dialogueDuckDb": outro.dialogue_duck_db, "bgmDuckDb": outro.bgm_duck_db, "assets": assets}
            manifest = {"version": "agentcut.render-manifest.v1", "output": str(output), "duration": project.duration,
                        "mainDuration": project.main_duration, "outro": outro_manifest}
            cleanup_manifest = []
            source_hashes: dict[str, str] = {}
            for track in project.video_tracks:
                if not track.enabled:
                    continue
                for clip in track.clips:
                    if not clip.cleanup_regions:
                        continue
                    source_hashes.setdefault(clip.source, digest(clip.source))
                    for index, item in enumerate(clip.cleanup_regions):
                        cleanup_manifest.append({"clipId": clip.id, "source": clip.source, "sourceSha256": source_hashes[clip.source],
                                                 "cleanupIndex": index, "mode": item.mode,
                                                 "region": {"x": item.x, "y": item.y, "width": item.width, "height": item.height},
                                                 "clipTime": {"start": item.start, "duration": item.duration},
                                                 "timelineTime": {"start": clip.start + item.start,
                                                                  "end": clip.start + item.start + (item.duration or clip.duration-item.start)},
                                                 "allowCaptionSafeBand": item.allow_caption_safe_band})
            manifest["cleanup"] = {"operationCount": len(cleanup_manifest), "operations": cleanup_manifest,
                                   "rollback": {"sourceFilesModified": False, "strategy": "remove cleanupRegions and re-render",
                                                "sourceSha256": source_hashes}}
            manifest["audioSafety"] = {"policy": asdict(project.master_audio_policy) if project.master_audio_policy else None,
                                       "releaseRequired": project.requires_master_audio_safety,
                                       "projected": _audio_coverage.get("projected"), "metrics": audio_metrics,
                                       "mastering": {"mode": "measured-two-pass" if two_pass else "single-pass",
                                                     "measurement": loudnorm_measurement,
                                                     "premasterAttenuationDb": premaster_attenuation_db if two_pass else 0.0,
                                                     "filter": mastering_filter}}
            review_path = project.release_gate.get("fullCutVisualReviewPath")
            release_required = bool(project.release_project or project.release_gate.get("required", False))
            if review_path:
                release_manifest = validate_release_output(
                    candidate, review_path,
                    conditional_source_count=int(_source_coverage.get("conditionalSourceCount") or 0),
                )
                release_manifest = {"required": release_required, **release_manifest, "final": str(output)}
            else:
                release_manifest = {
                    "required": release_required,
                    "status": "PENDING_POST_RENDER_VISUAL_REVIEW" if release_required else "NOT_REQUESTED",
                    "cleanRelease": False,
                    "final": str(output),
                    "finalSha256": digest(str(candidate)),
                    "reviewPath": None,
                    "hardGatePassed": False,
                    "conditionalSourceCount": int(_source_coverage.get("conditionalSourceCount") or 0),
                    "conditionalMachineAdmissionTriggersPlatformReplacement": False,
                    "automaticPlatformReplacementAllowed": False,
                    "platformMutationAuthorized": False,
                    "nextAction": "run release-validate against current final SHA" if release_required else None,
                }
            manifest["sourceAdmission"] = _source_coverage
            shot_recipes = command.summary.get("shotRecipes", _recipe_coverage)
            if shot_recipes.get("enabled"):
                shot_sidecar = Path(str(output) + ".shot-recipes.json")
                shot_sidecar_value = {
                    "schema": "agentcut.materialized_shot_recipes.v1",
                    "output": str(output), "outputSha256": digest(str(candidate)),
                    **shot_recipes,
                    "platformMutationAuthorized": False,
                }
                write_json_atomic(shot_sidecar, shot_sidecar_value)
                manifest["shotRecipes"] = {
                    **shot_recipes, "sidecarPath": str(shot_sidecar),
                    "sidecarSha256": digest(str(shot_sidecar)),
                }
            else:
                manifest["shotRecipes"] = shot_recipes
            manifest["assembly"] = {
                "mode": project.assembly_mode,
                "releaseEligible": not _source_coverage.get("conditionalSourceCount") and not project.hold_slots,
                "holdSlots": _hold_coverage,
                "conditionalSourceCount": int(_source_coverage.get("conditionalSourceCount") or 0),
                "platformMutationAuthorized": False,
            }
            manifest["finalVisualGate"] = final_visual_report or {
                "status": "NOT_REQUESTED", "hardGatePassed": False,
                "required": False, "platformMutationAuthorized": False,
            }
            manifest["releaseGate"] = release_manifest
            manifest_path = Path(str(output) + ".manifest.json")
            manifest["path"] = str(manifest_path)
            os.replace(candidate, output)
            try:
                failure_report.unlink()
            except FileNotFoundError:
                pass
            try:
                visual_failure_report.unlink()
            except FileNotFoundError:
                pass
            write_json_atomic(manifest_path, manifest)
            return RenderResult(str(output), project.duration, tuple(render_argv), audio_duration, manifest)
        finally:
            for temporary in temporary_paths:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    def render_many(self, sources: list[str | Path], *, workers: int | None = None,
                    overwrite: bool = False) -> list[BatchItemResult]:
        """Render projects concurrently in isolated processes, preserving input order."""
        if not sources:
            return []
        normalized = [str(Path(x).resolve()) for x in sources]
        indexed: dict[str, list[int]] = {}
        for i, source in enumerate(normalized):
            indexed.setdefault(source, []).append(i)
        results: list[BatchItemResult | None] = [None] * len(normalized)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_render_worker, source, self.ffmpeg, overwrite): source for source in normalized}
            for future in as_completed(futures):
                source = futures[future]
                item = future.result()
                for i in indexed[source]:
                    results[i] = item
        return [x for x in results if x is not None]
