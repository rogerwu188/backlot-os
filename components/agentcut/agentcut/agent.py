from __future__ import annotations

import json
import os
import shlex
import sys
import threading
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .engine import AgentCutEngine
from .audio_backend import audio_save_health
from .longtake import LongTakeValidator, longtake_preflight
from .giggle import finalize_first_last_submission, prepare_first_last_submission
from .runtime import runtime_identity
from .character_card import CharacterCardValidator, admit_character_card, generate_character_card_prompt, seedance_character_binding
from .bgm import generate_bgm, query_bgm
from .speech import generate_speech, list_speech_voices, query_speech


class AgentServer:
    """Concurrent NDJSON RPC server suitable for a parent agent such as Task2."""

    def __init__(self, engine: AgentCutEngine, workers: int | None = None) -> None:
        self.engine = engine
        self.workers = workers or min(32, (os.cpu_count() or 1))
        self._write_lock = threading.Lock()

    @staticmethod
    def _sha256(path: str) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def handle(self, request: dict[str, Any], event_callback: Any = None) -> dict[str, Any]:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        if method == "health":
            result = {**runtime_identity(__version__, self.engine.ffmpeg, self.engine.ffprobe),
                      "ffmpeg": self.engine.ffmpeg, "workers": self.workers,
                      "capabilities": {
                          "requireCutReason": True,
                          "continuityGate": {
                              "mode": "strict",
                              "requiredMetadata": ["cut_reason", "scene_id", "light_key", "axis_line", "eyeline"],
                          },
                          "requireBrandedOutro": True,
                          "sourceAdmissionGate": {
                              "mode": "per-shot-evidence",
                              "blockCode": "BLOCK_AGENTCUT_ASSEMBLY",
                              "actionNearDuplicateRatioMax": 0.15,
                              "cadenceFailBlocks": True,
                              "singleStillActionDefault": "block",
                              "requiredActionTrajectory": ["windup", "contact", "force", "result"],
                              "conditionalRoughAssembly": {
                                  "assemblyMode": "NON_RELEASE_ROUGH_ASSEMBLY",
                                  "evidenceSchema": "qingshan.conditional_machine_admission.v1",
                                  "exactSourceShaRequired": True,
                                  "rawCadenceFailPreserved": True,
                                  "defaultAllowedFailureCodes": ["video.periodic_duplicate", "audio.long_silence"],
                                  "releaseEligible": False,
                              },
                          },
                          "timelineHoldSlots": {
                              "modes": ["black", "placeholder"],
                              "preservesRuntime": True,
                              "releaseBlocking": True,
                              "replacementConditionRequired": True,
                          },
                          "releaseVisualGate": {
                              "validationMethod": "validateRelease",
                              "currentFinalShaBinding": True,
                              "hardGatePassedRequired": True,
                              "conditionalAdmissionAutoPlatformReplacement": False,
                              "platformMutationAuthorized": False,
                          },
                          "finalVisualGate": {
                              "capability": "CL2X-E28-FULLCUT-STAGNATION", "version": "1.0",
                              "validationMethod": "validateFinalVisual",
                              "renderPostflight": True, "atomicOutput": True,
                              "signals": ["pHash", "aHash", "pixelMotion"],
                              "defaultSampleFps": 2.0, "defaultMaxNearFreezeSeconds": 4.0,
                              "defaultMaxCompositionOccurrences": 2,
                              "defaultMaxCompositionRatio": 0.06,
                              "platformMutationAuthorized": False,
                          },
                          "narrativeGate": True,
                          "semanticBudget": {
                              "mode": "repeated-groups-only",
                              "defaultMaxGroupRatio": 0.15,
                              "configPath": "narrativeGate.maxSemanticGroupRatio",
                          },
                          "audioMastering": {
                              "mode": "measured-two-pass",
                              "atomicOutput": True,
                              "postflightHardGates": ["integratedLoudness", "truePeak", "clippedSamples", "duration"],
                          },
                          "videoBoundaryMaterialization": {
                              "mode": "cfr-half-open",
                              "boundaryRounding": "nearest-frame-half-up",
                              "handoffGuardFrames": 0.5,
                              "boundarySentinelFrames": 1,
                              "sentinelVisible": False,
                              "repeatLastFrame": False,
                              "visibleTailPadding": False,
                              "audioTiming": "exact-unmodified",
                              "blackFrameHardCutRegression": True,
                              "releaseBlackFramePolicy": {"amount": 95, "threshold": 32},
                              "cadenceRegression": True,
                          },
                          "burnedSubtitles": True,
                          "renderMany": True,
                          "longTake": {
                              "capability": "CL2X-352", "version": "1.0",
                              "preflightMethod": "longTakePreflight",
                              "validationMethod": "validateLongTake",
                              "defaultSceneThreshold": 0.20,
                          },
                          "giggleFirstLast": {
                              "capability": "CL2X-353", "version": "1.0",
                              "generation_mode": "image_to_video_first_last",
                              "endpoint": "/api/v1/generation/image-to-video",
                              "requiredRoles": ["start_frame", "end_frame"],
                              "silentOmniFallbackAllowed": False,
                          },
                          "characterCanonicalCard": {
                              "capability": "CL2X-358", "version": "1.0",
                              "manifestSchema": "agentcut.character_canonical_card.v1",
                              "layout": "headshot-left_then-fullbody-front-side-back",
                              "minimumFullBodyViews": 3,
                              "seedanceBinding": "[[char_n]]",
                              "hardAdmissionGate": True,
                          },
                          "bgmGeneration": {
                              "capability": "AGENTCUT-BGM-001", "version": "1.0",
                              "provider": "giggle.pro", "instrumentalOnly": True,
                              "generationMethod": "generateBgm", "queryMethod": "queryBgm",
                              "credentialEnv": "GIGGLE_API_KEY", "signedUrlsReturned": False,
                              "atomicDownload": True, "commercialMetadataRequiredForRelease": True,
                          },
                          "speechGeneration": {
                              "capability": "AGENTCUT-SPEECH-001", "version": "1.0",
                              "provider": "giggle.pro", "generationMode": "text_to_audio",
                              "listVoicesMethod": "listSpeechVoices",
                              "generationMethod": "generateSpeech", "queryMethod": "querySpeech",
                              "credentialEnv": "GIGGLE_API_KEY", "signedUrlsReturned": False,
                              "atomicDownload": True, "directTrack": "Audio.Dialogue",
                              "commercialMetadataRequiredForRelease": True,
                          },
                          "shotRecipeRegistry": {
                              "capability": "AGENTCUT-DIRECTOR-RECIPES-001", "version": "1.0",
                              "registryId": "agentcut.short_drama.director_recipes",
                              "registryVersion": "1.0.0", "recipeCount": 27,
                              "listMethod": "listShotRecipes", "repairMethod": "mapShotRecipeRepairs",
                              "secondsAuthoritative": True, "frameRounding": "nearest-half-up",
                              "supportedFps": [24, 30], "supports9x16": True,
                              "remotionRequired": False, "audioAssetsImported": False,
                              "layer": "per_shot_director_execution",
                              "styleTemplateBehavior": "preserve_project_style",
                              "styleOverrideAllowed": False,
                              "preservesExistingHardGates": True,
                              "platformMutationAuthorized": False,
                          },
                      },
                      "audioSave": audio_save_health(self.engine.ffmpeg)}
        elif method in {"validate", "validateMedia"}:
            report = self.engine.validate(params["project"], strict_media=method == "validateMedia" or bool(params.get("strictMedia", False)))
            result = report.to_dict()
        elif method == "validateRelease":
            result = self.engine.validate_release(
                params["final"], params["review"], project=params.get("project"),
            )
        elif method == "validateFinalVisual":
            result = self.engine.validate_final_visual(
                params["final"], project=params.get("project"),
                report=params.get("report"), policy=params.get("policy"),
            )
        elif method == "compile":
            compiled = self.engine.compile(params["project"], overwrite=bool(params.get("overwrite", False)))
            result = {"argv": compiled.argv, "command": shlex.join(compiled.argv), "filterGraph": compiled.filter_graph, "summary": compiled.summary}
        elif method == "listShotRecipes":
            result = self.engine.list_shot_recipes()
        elif method == "mapShotRecipeRepairs":
            result = self.engine.map_shot_recipe_repairs(
                params["project"], aggregate_problems=params.get("problems"),
            )
        elif method == "render":
            progress_callback = None
            if params.get("progress") and event_callback:
                event_callback({"phase": "rendering", "time": 0.0, "progress": 0.0})
                progress_callback = lambda value: event_callback({"phase": "rendering", "time": value.time, "duration": value.duration, "progress": value.progress})
            rendered = self.engine.render(params["project"], overwrite=bool(params.get("overwrite", False)), on_progress=progress_callback)
            result = {"output": rendered.output, "duration": rendered.duration, "audioDuration": rendered.audio_duration, "manifest": rendered.manifest}
            result = {k: v for k, v in result.items() if v is not None}
            if params.get("includeHash"):
                result["sha256"] = self._sha256(rendered.output)
            if params.get("includeCommand"):
                result["command"] = rendered.command
        elif method == "renderMany":
            rendered = self.engine.render_many(params["projects"], workers=params.get("workers"), overwrite=bool(params.get("overwrite", False)))
            result = {"items": [asdict(x) for x in rendered]}
        elif method in {"transformProject", "trimProject"}:
            transformed = self.engine.transform(
                params["project"], params["plan"], dry_run=bool(params.get("dryRun", True)),
                output=params.get("output"), audit_path=params.get("auditPath"),
                strict_media=bool(params.get("strictMedia", False)),
                require_cut_reason=bool(params.get("requireCutReason", False)),
            )
            result = transformed.summary(
                include_project=bool(params.get("includeProject", False)),
                include_audit=bool(params.get("includeAudit", False)),
            )
        elif method == "rollbackProject":
            rolled_back = self.engine.rollback(
                params["audit"], output=params.get("output"), dry_run=bool(params.get("dryRun", False))
            )
            if not params.get("includeProject", False):
                rolled_back.pop("project", None)
            result = rolled_back
        elif method == "longTakePreflight":
            result = longtake_preflight(params["request"])
        elif method == "validateLongTake":
            result = LongTakeValidator(self.engine.ffmpeg, self.engine.ffprobe).validate(
                params["video"], anchor_times=params.get("anchorTimes", []),
                scene_threshold=float(params.get("sceneThreshold", 0.20)),
                anchor_window=float(params.get("anchorWindow", 0.75)),
                continuous_camera_required=bool(params.get("continuousCameraRequired", True)),
            )
        elif method == "prepareFirstLastGeneration":
            result = prepare_first_last_submission(
                params["task"], client=params.get("client", "tools/giggle_api_client.py"),
                include_command=bool(params.get("includeCommand", False)),
            )
        elif method == "finalizeFirstLastGeneration":
            result = finalize_first_last_submission(
                params["task"], params["video"], params["taskId"],
                ffmpeg=self.engine.ffmpeg, ffprobe=self.engine.ffprobe,
                scene_threshold=float(params.get("sceneThreshold", 0.20)),
            )
        elif method == "generateCharacterCardPrompt":
            result = generate_character_card_prompt(params["description"])
        elif method == "validateCharacterCard":
            result = CharacterCardValidator(self.engine.ffprobe).validate(params["manifest"])
        elif method == "bindSeedanceCharacter":
            result = seedance_character_binding(params["manifest"], ffprobe=self.engine.ffprobe)
        elif method == "admitCharacterCard":
            result = admit_character_card(
                params["manifest"], params["registry"], ffprobe=self.engine.ffprobe,
                dry_run=bool(params.get("dryRun", True)), output=params.get("output"),
            )
        elif method == "generateBgm":
            result = generate_bgm(
                params["prompt"], params["outputDir"],
                poll_interval_seconds=float(params.get("pollIntervalSeconds", 20)),
                timeout_seconds=float(params.get("timeoutSeconds", 1500)),
                overwrite=bool(params.get("overwrite", False)), progress=event_callback,
            )
        elif method == "queryBgm":
            result = query_bgm(params["taskId"])
            result.pop("_urls", None)
        elif method == "listSpeechVoices":
            result = list_speech_voices()
        elif method == "generateSpeech":
            result = generate_speech(
                params["text"], params["outputDir"],
                voice_id=params["voiceId"], emotion=params["emotion"],
                speed=float(params.get("speed", 1)),
                poll_interval_seconds=float(params.get("pollIntervalSeconds", 5)),
                timeout_seconds=float(params.get("timeoutSeconds", 120)),
                overwrite=bool(params.get("overwrite", False)),
                file_name=params.get("fileName", "dialogue_voice.mp3"),
                progress=event_callback,
            )
        elif method == "querySpeech":
            result = query_speech(params["taskId"])
            result.pop("_urls", None)
        else:
            raise ValueError(f"unknown method: {method!r}")
        return {"id": request_id, "ok": True, "result": result}

    def _respond(self, request: Any, output: TextIO) -> None:
        request_id = request.get("id") if isinstance(request, dict) else None
        try:
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            def emit(data: dict[str, Any]) -> None:
                self._write({"id": request_id, "event": "progress", "data": data}, output)
            response = self.handle(request, emit)
        except Exception as exc:
            response = {"id": request_id, "ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}
        self._write(response, output)

    def _write(self, payload: dict[str, Any], output: TextIO) -> None:
        with self._write_lock:
            output.write(json.dumps(payload, ensure_ascii=False) + "\n")
            output.flush()

    def serve(self, input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout) -> None:
        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="agentcut") as pool:
            for line in input_stream:
                if not line.strip():
                    continue
                try:
                    request = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._respond({"id": None, "method": None, "params": {"_parseError": str(exc)}}, output_stream)
                    continue
                pool.submit(self._respond, request, output_stream)
