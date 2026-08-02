from __future__ import annotations

import argparse
import json
import shlex
import sys

from .engine import AgentCutEngine
from .errors import AgentCutError
from .agent import AgentServer
from .isolation import isolate_dialogue
from .audio_backend import audio_save_health, run_demucs_with_safe_save
from .longtake import LongTakeValidator, longtake_preflight
from .giggle import finalize_first_last_submission, prepare_first_last_submission
from .character_card import CharacterCardValidator, admit_character_card, generate_character_card_prompt, seedance_character_binding
from .bgm import generate_bgm, query_bgm
from .speech import generate_speech, list_speech_voices, query_speech


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentcut", description="Agent-friendly headless video editor")
    parser.add_argument("--ffmpeg", default="auto", help="FFmpeg executable (default: bundled binary, then PATH)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="Report version, immutable runtime hash, binaries, and production capabilities")
    release_validate = sub.add_parser("release-validate", help="Bind a full-cut visual review to the current final SHA")
    release_validate.add_argument("final", help="Current final video file")
    release_validate.add_argument("review", help="Full-cut visual review JSON")
    release_validate.add_argument("--project", help="Optional AgentCut project for source-admission evidence")
    final_visual = sub.add_parser("final-visual-validate", help="Hard-gate a rendered full cut for near-freeze and repeated composition")
    final_visual.add_argument("final", help="Rendered final/candidate video")
    final_visual.add_argument("--project", help="Optional AgentCut project for dialogue/action evidence and rollback mapping")
    final_visual.add_argument("--policy", help="Optional finalVisualPolicy JSON object file")
    final_visual.add_argument("--report", required=True, help="Machine-readable JSON report path")
    for name in ("validate", "compile", "render"):
        p = sub.add_parser(name)
        p.add_argument("project", help="Project JSON file")
        if name in {"compile", "render"}:
            p.add_argument("--overwrite", action="store_true")
        if name == "validate":
            p.add_argument("--strict-media", action="store_true", help="Probe sources and reject stream, bounds, and video coverage errors")
    batch = sub.add_parser("render-batch", help="Render multiple projects concurrently")
    batch.add_argument("projects", nargs="+", help="Project JSON files")
    batch.add_argument("--workers", type=int, default=None, help="Parallel worker processes (default: CPU count)")
    batch.add_argument("--overwrite", action="store_true")
    agent = sub.add_parser("agent", help="Run concurrent NDJSON agent server on stdin/stdout")
    agent.add_argument("--workers", type=int, default=None, help="Maximum concurrent requests")
    transform = sub.add_parser("transform", aliases=["trim-project"], help="Apply a deterministic timeline trim plan")
    transform.add_argument("project", help="Input project JSON")
    transform.add_argument("plan", help="Trim plan JSON")
    transform.add_argument("--output", help="Transformed project path (required unless --dry-run)")
    transform.add_argument("--audit", help="Deterministic audit/rollback JSON path")
    transform.add_argument("--dry-run", action="store_true", help="Return diff without writing files")
    transform.add_argument("--strict-media", action="store_true", help="Run strict media and video-gap validation before writing")
    transform.add_argument("--require-cut-reason", action="store_true", help="Require a non-empty cutReason on every trim operation")
    transform.add_argument("--include-project", action="store_true", help="Include transformed project in JSON response")
    rollback = sub.add_parser("rollback", help="Restore the exact pre-transform project from an audit")
    rollback.add_argument("audit", help="Audit JSON produced by transform")
    rollback.add_argument("--output", required=True, help="Restored project path")
    rollback.add_argument("--dry-run", action="store_true")
    isolate = sub.add_parser("dialogue-isolate", help="Create a local vocal candidate and contamination report from WAV")
    isolate.add_argument("input", help="Source WAV")
    isolate.add_argument("--output", required=True, help="Vocal candidate WAV")
    isolate.add_argument("--report", required=True, help="JSON contamination/artifact report")
    isolate.add_argument("--confidence-threshold", type=float, default=0.8)
    isolate.add_argument("--overwrite", action="store_true")
    save_health = sub.add_parser("isolation-health", help="Probe audio-save backends with an actual WAV write")
    demucs = sub.add_parser("demucs-isolate", help="Run Demucs with fail-fast save-backend fallback and provenance")
    demucs.add_argument("input", help="Source audio")
    demucs.add_argument("--output-dir", required=True)
    demucs.add_argument("--report", required=True)
    demucs.add_argument("--model", default="htdemucs")
    demucs.add_argument("--expected-model-sha256")
    demucs.add_argument("--overwrite", action="store_true")
    longtake_preflight_parser = sub.add_parser("longtake-preflight", help="Fail unsafe multi-image continuous-camera requests before paid submission")
    longtake_preflight_parser.add_argument("request", help="Long-take request JSON")
    longtake_validate = sub.add_parser("longtake-validate", help="Detect hard cuts in a generated continuous-camera candidate")
    longtake_validate.add_argument("video", help="Generated candidate video")
    longtake_validate.add_argument("--anchor-times", default="", help="Comma-separated temporal anchor times")
    longtake_validate.add_argument("--scene-threshold", type=float, default=0.20)
    longtake_validate.add_argument("--anchor-window", type=float, default=0.75)
    first_last_prepare = sub.add_parser("first-last-prepare", help="Validate and compile a Giggle first/last-frame task before paid submission")
    first_last_prepare.add_argument("task", help="First/last generation task JSON")
    first_last_prepare.add_argument("--client", default="tools/giggle_api_client.py")
    first_last_prepare.add_argument("--include-command", action="store_true")
    first_last_finalize = sub.add_parser("first-last-finalize", help="Create a role/endpoint/SHA receipt and enforce hard-cut continuity")
    first_last_finalize.add_argument("task", help="First/last generation task JSON")
    first_last_finalize.add_argument("video", help="Downloaded generated candidate")
    first_last_finalize.add_argument("--task-id", required=True)
    first_last_finalize.add_argument("--scene-threshold", type=float, default=0.20)
    character_prompt = sub.add_parser("character-card-prompt", help="Compile a canonical three-view character-card prompt")
    character_prompt.add_argument("description", help="Structured character description JSON")
    character_validate = sub.add_parser("character-card-validate", help="Hard-validate a canonical character-card manifest")
    character_validate.add_argument("manifest")
    character_bind = sub.add_parser("character-card-bind", help="Emit an admitted Seedance [[char_n]] binding")
    character_bind.add_argument("manifest")
    character_admit = sub.add_parser("character-card-admit", help="Validate and register a canonical character card")
    character_admit.add_argument("manifest")
    character_admit.add_argument("registry")
    character_admit.add_argument("--output")
    character_admit.add_argument("--write", action="store_true", help="Write the updated registry; default is dry-run")
    bgm_generate = sub.add_parser("bgm-generate", help="Generate instrumental BGM, poll, and atomically download candidates")
    bgm_generate.add_argument("prompt", help="Exact music description sent to the provider")
    bgm_generate.add_argument("--output-dir", required=True)
    bgm_generate.add_argument("--poll-interval", type=float, default=20)
    bgm_generate.add_argument("--timeout", type=float, default=1500)
    bgm_generate.add_argument("--overwrite", action="store_true")
    bgm_query = sub.add_parser("bgm-query", help="Query an existing BGM generation task without exposing signed URLs")
    bgm_query.add_argument("task_id")
    sub.add_parser("speech-voices", help="List Giggle speech voices")
    speech_generate = sub.add_parser("speech-generate", help="Generate dialogue speech and atomically download an MP3")
    speech_generate.add_argument("text", help="Exact dialogue text sent to the provider")
    speech_generate.add_argument("--voice-id", required=True)
    speech_generate.add_argument("--emotion", required=True)
    speech_generate.add_argument("--output-dir", required=True)
    speech_generate.add_argument("--speed", type=float, default=1)
    speech_generate.add_argument("--file-name", default="dialogue_voice.mp3")
    speech_generate.add_argument("--poll-interval", type=float, default=5)
    speech_generate.add_argument("--timeout", type=float, default=120)
    speech_generate.add_argument("--overwrite", action="store_true")
    speech_query = sub.add_parser("speech-query", help="Query an existing speech generation task without exposing signed URLs")
    speech_query.add_argument("task_id")
    sub.add_parser("shot-recipe-list", help="List the curated live-action/generated short-drama director recipe registry")
    recipe_repairs = sub.add_parser("shot-recipe-repairs", help="Map recipe or aggregate QA problems to clip and phase repair tasks")
    recipe_repairs.add_argument("project", help="AgentCut project JSON")
    recipe_repairs.add_argument("--problems", help="Optional aggregate problem array JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    engine = AgentCutEngine(args.ffmpeg)
    try:
        if args.command == "health":
            result = AgentServer(engine, workers=1).handle({"id": "health", "method": "health", "params": {}})["result"]
            print(json.dumps({"ok": result["ready"], **result}, ensure_ascii=False))
            return 0 if result["ready"] else 2
        if args.command == "agent":
            if args.workers is not None and args.workers <= 0:
                raise ValueError("--workers must be positive")
            AgentServer(engine, args.workers).serve()
            return 0
        if args.command == "release-validate":
            result = engine.validate_release(args.final, args.review, project=args.project)
            print(json.dumps({"ok": result["cleanRelease"], **result}, ensure_ascii=False))
            return 0 if result["cleanRelease"] else 2
        if args.command == "final-visual-validate":
            policy = None
            if args.policy:
                with open(args.policy, encoding="utf-8") as stream:
                    policy = json.load(stream)
            result = engine.validate_final_visual(
                args.final, project=args.project, report=args.report, policy=policy,
            )
            print(json.dumps({"ok": result["hardGatePassed"], **result}, ensure_ascii=False))
            return 0 if result["hardGatePassed"] else 2
        if args.command == "shot-recipe-list":
            print(json.dumps({"ok": True, **engine.list_shot_recipes()}, ensure_ascii=False))
            return 0
        if args.command == "shot-recipe-repairs":
            problems = None
            if args.problems:
                with open(args.problems, encoding="utf-8") as stream:
                    problems = json.load(stream)
                if not isinstance(problems, list):
                    raise ValueError("--problems must contain a JSON array")
            result = engine.map_shot_recipe_repairs(args.project, aggregate_problems=problems)
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0
        if args.command == "render-batch":
            if args.workers is not None and args.workers <= 0:
                raise ValueError("--workers must be positive")
            results = engine.render_many(args.projects, workers=args.workers, overwrite=args.overwrite)
            payload = {"ok": all(x.ok for x in results), "results": [x.__dict__ for x in results]}
            print(json.dumps(payload, ensure_ascii=False))
            return 0 if payload["ok"] else 2
        if args.command in {"transform", "trim-project"}:
            transformed = engine.transform(
                args.project, args.plan, dry_run=args.dry_run, output=args.output,
                audit_path=args.audit, strict_media=args.strict_media,
                require_cut_reason=args.require_cut_reason,
            )
            payload = {"ok": True, **transformed.summary(include_project=args.include_project)}
            print(json.dumps(payload, ensure_ascii=False))
            return 0 if transformed.valid else 2
        if args.command == "rollback":
            rolled_back = engine.rollback(args.audit, output=args.output, dry_run=args.dry_run)
            rolled_back.pop("project", None)
            print(json.dumps({"ok": True, **rolled_back}, ensure_ascii=False))
            return 0
        if args.command == "dialogue-isolate":
            if not 0 <= args.confidence_threshold <= 1:
                raise ValueError("--confidence-threshold must be between 0 and 1")
            result = isolate_dialogue(engine.ffmpeg, engine.ffprobe, args.input, args.output, args.report,
                                      threshold=args.confidence_threshold, overwrite=args.overwrite)
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0 if result["separationPassed"] else 2
        if args.command == "isolation-health":
            health = audio_save_health(engine.ffmpeg)
            print(json.dumps({"ok": health["ready"], "audioSave": health}, ensure_ascii=False))
            return 0 if health["ready"] else 2
        if args.command == "demucs-isolate":
            result = run_demucs_with_safe_save(engine.ffmpeg, args.input, args.output_dir, args.report,
                                               model=args.model, expected_model_sha256=args.expected_model_sha256,
                                               overwrite=args.overwrite)
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0
        if args.command == "longtake-preflight":
            result = longtake_preflight(args.request)
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0 if result["allowed"] else 2
        if args.command == "longtake-validate":
            anchors = [float(value.strip()) for value in args.anchor_times.split(",") if value.strip()]
            result = LongTakeValidator(engine.ffmpeg, engine.ffprobe).validate(
                args.video, anchor_times=anchors, scene_threshold=args.scene_threshold,
                anchor_window=args.anchor_window,
            )
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0 if result["valid"] else 2
        if args.command == "first-last-prepare":
            result = prepare_first_last_submission(args.task, client=args.client, include_command=args.include_command)
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0
        if args.command == "first-last-finalize":
            result = finalize_first_last_submission(
                args.task, args.video, args.task_id, ffmpeg=engine.ffmpeg,
                ffprobe=engine.ffprobe, scene_threshold=args.scene_threshold,
            )
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0 if result["accepted"] else 2
        if args.command == "character-card-prompt":
            result = generate_character_card_prompt(args.description)
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0
        if args.command == "character-card-validate":
            result = CharacterCardValidator(engine.ffprobe).validate(args.manifest)
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0 if result["valid"] else 2
        if args.command == "character-card-bind":
            result = seedance_character_binding(args.manifest, ffprobe=engine.ffprobe)
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0 if result["bindingAllowed"] else 2
        if args.command == "character-card-admit":
            result = admit_character_card(
                args.manifest, args.registry, ffprobe=engine.ffprobe,
                dry_run=not args.write, output=args.output,
            )
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0 if result["valid"] else 2
        if args.command == "bgm-generate":
            result = generate_bgm(
                args.prompt, args.output_dir, poll_interval_seconds=args.poll_interval,
                timeout_seconds=args.timeout, overwrite=args.overwrite,
            )
            print(json.dumps({"ok": result["status"] == "completed", **result}, ensure_ascii=False))
            return 0 if result["status"] == "completed" else 2
        if args.command == "bgm-query":
            result = query_bgm(args.task_id)
            result.pop("_urls", None)
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0
        if args.command == "speech-voices":
            result = list_speech_voices()
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0
        if args.command == "speech-generate":
            result = generate_speech(
                args.text, args.output_dir, voice_id=args.voice_id, emotion=args.emotion,
                speed=args.speed, file_name=args.file_name,
                poll_interval_seconds=args.poll_interval, timeout_seconds=args.timeout,
                overwrite=args.overwrite,
            )
            print(json.dumps({"ok": result["status"] == "completed", **result}, ensure_ascii=False))
            return 0 if result["status"] == "completed" else 2
        if args.command == "speech-query":
            result = query_speech(args.task_id)
            result.pop("_urls", None)
            print(json.dumps({"ok": True, **result}, ensure_ascii=False))
            return 0
        if args.command == "validate":
            report = engine.validate(args.project, strict_media=args.strict_media)
            payload = {"ok": True, **report.to_dict()}
        elif args.command == "compile":
            command = engine.compile(args.project, overwrite=args.overwrite)
            payload = {"ok": True, "command": shlex.join(command.argv), "filterGraph": command.filter_graph, "summary": command.summary}
        else:
            result = engine.render(args.project, overwrite=args.overwrite)
            payload = {"ok": True, "output": result.output, "duration": result.duration, "audioDuration": result.audio_duration, "manifest": result.manifest}
        print(json.dumps(payload, ensure_ascii=False))
        if args.command == "validate" and not payload["valid"]:
            return 2
        return 0
    except (AgentCutError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
