import unittest
import io
import json
import os
import tempfile
import subprocess
import hashlib
from pathlib import Path
from unittest.mock import Mock, patch

from agentcut import AgentCutEngine, AgentCutError, RenderProgress, RenderResult, ValidationError
from agentcut.agent import AgentServer
from agentcut.validation import MediaValidator, validate_release_project_contract, validate_replacement_bindings
from agentcut.transform import content_hash
from agentcut.isolation import isolation_confidence
from agentcut.audio_backend import audio_save_health, require_audio_save_backend


def project():
    return {
        "version": "1.0", "output": {"path": "out.mp4", "width": 1280, "height": 720},
        "timeline": {
            "videoTracks": [{"id": "A", "clips": [{"source": "a.mp4", "start": 1, "in": 2, "duration": 4, "transitionIn": {"type": "fade", "duration": .5}}]}],
            "audioTracks": [{"id": "voice", "clips": [{"source": "v.wav", "start": .25, "duration": 5, "volume": .8}]}]
        }
    }


CHINESE_FONT = os.environ.get("AGENTCUT_SUBTITLE_FONT", "/System/Library/Fonts/STHeiti Medium.ttc")


def subtitled_project():
    data = project()
    data["requireBurnedSubtitles"] = True
    data["expectedDialogueIds"] = ["D1", "D2"]
    data["timeline"]["subtitleTracks"] = [{
        "id": "zh-CN",
        "style": {"font": CHINESE_FONT, "size": 44, "outline": 3, "alignment": "bottom-center",
                  "margins": {"left": 72, "right": 72, "top": 96, "bottom": 160}, "wrap": 16},
        "clips": [
            {"id": "c1", "dialogue_id": "D1", "text": "半夜送礼", "start": 0, "duration": 2},
            {"id": "c2", "dialogue_id": "D2", "text": "不怕犯忌？", "start": 2, "duration": 2},
        ],
    }]
    return data


def trim_project():
    def clip(clip_id, dialogue_id, beat_id, source, start):
        return {"id": clip_id, "metadata": {"dialogue_id": dialogue_id, "beat_id": beat_id},
                "source": source, "start": start, "in": 0, "duration": 1}
    return {
        "version": "1.0", "output": {"path": "out.mp4"},
        "timeline": {
            "videoTracks": [{"id": "A", "clips": [
                clip("v-d1", "D1", "E18R", "v.mp4", 0), clip("v-d2", "D2", "E18R", "v.mp4", 1),
                clip("v-b05", "D3", "B05", "v.mp4", 2),
            ]}],
            "audioTracks": [{"id": "dialogue", "clips": [
                clip("a-d1", "D1", "E18R", "a.wav", 0), clip("a-d2", "D2", "E18R", "a.wav", 1),
                clip("a-b05", "D3", "B05", "a.wav", 2),
            ]}],
        },
    }


def trim_plan():
    return {
        "version": "1.0", "expectedOperationCount": 2, "expectedTotalTrim": 0.4,
        "operations": [
            {"id": "trim-d1", "match": {"dialogueId": "D1"}, "headTrim": 0.2,
             "contentGuard": "silence-head", "requiredTrackKinds": ["video", "audio"]},
            {"id": "trim-d2", "match": {"dialogueId": "D2"}, "headTrim": 0.2,
             "contentGuard": "silence-head", "requiredTrackKinds": ["video", "audio"]},
        ],
        "protections": {"beatIds": ["B05"]},
        "options": {"ripple": True, "requireSynchronizedStart": True, "maxHeadTrim": 0.2, "preserveTrackOrder": True},
    }


class AgentCutTests(unittest.TestCase):
    E27_N09_CADENCE = Path("/Users/rogerwu/qingshan_short_drama/qa/e27_writer_agent_v040_video_visualfix_r1_20260720/E27-N09-WRITER-AGENT-V040-VIDEO-VISUALFIX-R1_frame_cadence.json")
    E27_N04_CADENCE = Path("/Users/rogerwu/qingshan_short_drama/qa/e27_writer_agent_v040_video_v1_20260720/E27-N04-WRITER-AGENT-V040-VIDEO-V1_frame_cadence.json")
    E27_N19_CADENCE = Path("/Users/rogerwu/qingshan_short_drama/qa/e27_writer_agent_v040_video_native_text_r2_20260720/E27-N19-WRITER-AGENT-V040-VIDEO-NATIVE-TEXT-R2_frame_cadence.json")
    E28_V3_FINAL = Path("/Users/rogerwu/qingshan_short_drama/exports/e28/final/E28_AGENTCUT_V3_WRITER_AGENT_V050_FINAL.mp4")
    E28_V3_PROJECT = Path("/Users/rogerwu/qingshan_short_drama/configs/e28_agentcut_v3_writer_agent_v050_release_candidate_20260721.json")
    E28_V4_FINAL = Path("/Users/rogerwu/qingshan_short_drama/exports/e28/agentcut_v4_midsection_recut_20260721/E28_AGENTCUT_V4_MIDSECTION_RECUT_NOT_FINAL.mp4")
    E28_V4_PROJECT = Path("/Users/rogerwu/qingshan_short_drama/configs/e28_agentcut_v4_midsection_recut_20260721.json")
    E28_CL2X517_PROJECT = Path("/Users/rogerwu/qingshan_short_drama/configs/e28_agentcut_v1_cl2x517_u09_hold_20260721.json")

    @staticmethod
    def _admission_project(shot_id, cadence_path, *, reference_mode="generated_video", admission="PASS"):
        report = json.loads(Path(cadence_path).read_text(encoding="utf-8"))
        return {
            "version": "1.0",
            "output": {"path": f"{shot_id}.mp4", "width": 720, "height": 1280, "fps": 24},
            "sourceAdmissionPolicy": {"enabled": True, "maxActionNearDuplicateRatio": 0.15},
            "timeline": {"videoTracks": [{"id": "Video.Main", "clips": [{
                "id": f"{shot_id}-VIDEO", "source": report["video"], "start": 0, "duration": 1,
                "metadata": {
                    "shot_id": shot_id, "action_required": True,
                    "action_trajectory": {
                        "windup": "subject prepares the move", "contact": "subject reaches the target",
                        "force": "force transfers through the target", "result": "visible state changes",
                    },
                    "source_reference_mode": reference_mode,
                    "cadence_report_path": str(cadence_path), "source_admission": admission,
                },
            }]}]},
        }

    @staticmethod
    def _conditional_rough_project(directory, *, evidence_failure="video.periodic_duplicate"):
        root = Path(directory)
        source = root / "U02.mp4"
        source.write_bytes(b"immutable conditional candidate")
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        cadence = root / "U02_cadence.json"
        cadence.write_text(json.dumps({
            "status": "FAIL", "video": str(source),
            "periodic_duplicates": {"near_duplicate_ratio": 0.24},
        }), encoding="utf-8")
        raw_review = root / "raw_review.json"
        raw_review.write_text(json.dumps({
            "schema": "qingshan.review_many.result.v2", "status": "CONTENT_FAIL",
            "items": [{
                "media_path": str(source), "media_sha256": source_sha, "status": "FAIL",
                "required_capability_failures": [],
                "issues": [{"rule_id": evidence_failure, "blocking": True}],
            }],
        }), encoding="utf-8")
        evidence = root / "conditional_admission.json"
        evidence.write_text(json.dumps({
            "schema": "qingshan.conditional_machine_admission.v1",
            "raw_review": str(raw_review),
            "raw_review_sha256": hashlib.sha256(raw_review.read_bytes()).hexdigest(),
            "items": [{
                "unit_id": "U02", "decision": "CONDITIONAL_MACHINE_ADMISSION",
                "candidate_path": str(source), "candidate_sha256": source_sha,
                "raw_qa_status": "FAIL", "raw_failures": [evidence_failure],
                "confidence": 0.86, "selection_reason": "best available non-release review source",
                "rollback_point": "restore the pre-assembly project",
                "replacement_condition": "replace when a clean U02 passes cadence",
            }],
        }), encoding="utf-8")
        project_value = {
            "version": "1.0", "assemblyMode": "NON_RELEASE_ROUGH_ASSEMBLY",
            "metadata": {"releaseAllowed": False, "platformUploadAllowed": False},
            "output": {"path": str(root / "rough.mp4"), "width": 720, "height": 1280, "fps": 24},
            "sourceAdmissionPolicy": {
                "enabled": True, "requirePerShotCadence": True,
                "maxActionNearDuplicateRatio": 0.15,
                "allowConditionalCadenceFailForRoughAssembly": True,
                "allowedConditionalFailureCodes": ["video.periodic_duplicate", "audio.long_silence"],
                "conditionalAdmissionEvidencePath": str(evidence),
            },
            "timeline": {
                "videoTracks": [{"id": "Video.Main", "clips": [{
                    "id": "U02-VIDEO", "source": str(source), "start": 0, "duration": 2,
                    "metadata": {
                        "unit_id": "U02", "shot_id": "U02", "action_required": True,
                        "action_trajectory": {"windup": "raise", "contact": "touch", "force": "push", "result": "opens"},
                        "source_reference_mode": "generated_video", "cadence_report_path": str(cadence),
                        "source_admission": "CONDITIONAL_MACHINE_ADMISSION", "source_sha256": source_sha,
                    },
                }]}],
                "holdSlots": [{
                    "id": "U09", "start": 2, "duration": 1, "mode": "black",
                    "reason": "source intentionally withheld for replacement",
                    "replacementCondition": "replace U09 and rerun full QA", "releaseBlocking": True,
                }],
            },
        }
        return project_value, source, evidence

    def test_conditional_exact_sha_is_admitted_only_for_non_release_rough_assembly(self):
        with tempfile.TemporaryDirectory() as directory:
            data, _source, _evidence = self._conditional_rough_project(directory)
            report = AgentCutEngine().validate(data)
            self.assertTrue(report.valid, [issue.to_dict() for issue in report.issues])
            coverage = report.coverage["sourceAdmission"]
            self.assertEqual(coverage["status"], "PASS_NON_RELEASE_ROUGH_ASSEMBLY")
            self.assertFalse(coverage["releaseEligible"])
            self.assertEqual(coverage["conditionallyAdmittedCount"], 1)
            item = coverage["items"][0]
            self.assertEqual(item["cadenceStatus"], "FAIL")
            self.assertEqual(item["conditionalEvidence"]["rawQaStatus"], "FAIL")
            self.assertEqual(item["conditionalEvidence"]["rawFailures"], ["video.periodic_duplicate"])
            self.assertIn("original_cadence_fail", item["warnings"])
            self.assertEqual(report.coverage["holdSlots"]["unresolvedCount"], 1)
            self.assertFalse(report.coverage["holdSlots"]["releaseEligible"])
            compiled = AgentCutEngine().compile(data)
            self.assertEqual(compiled.summary["assembly"]["mode"], "NON_RELEASE_ROUGH_ASSEMBLY")
            self.assertEqual(compiled.summary["assembly"]["holdSlots"][0]["id"], "U09")

    def test_conditional_admission_rejects_missing_evidence_sha_mismatch_and_severe_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            data, source, evidence = self._conditional_rough_project(directory)
            data["sourceAdmissionPolicy"].pop("conditionalAdmissionEvidencePath")
            missing = AgentCutEngine().validate(data)
            self.assertFalse(missing.valid)
            self.assertIn("conditional_admission_evidence_missing", missing.coverage["sourceAdmission"]["items"][0]["reasons"])

            data, source, evidence = self._conditional_rough_project(directory)
            source.write_bytes(b"mutated after evidence approval")
            mismatch = AgentCutEngine().validate(data)
            self.assertFalse(mismatch.valid)
            self.assertIn("conditional_actual_source_sha_mismatch", mismatch.coverage["sourceAdmission"]["items"][0]["reasons"])

        with tempfile.TemporaryDirectory() as directory:
            data, _source, _evidence = self._conditional_rough_project(directory, evidence_failure="identity.character_mismatch")
            severe = AgentCutEngine().validate(data)
            self.assertFalse(severe.valid)
            reasons = severe.coverage["sourceAdmission"]["items"][0]["reasons"]
            self.assertTrue(any(reason.startswith("conditional_failure_not_rough_eligible:") for reason in reasons))

    def test_conditional_admission_cross_checks_raw_review_content_and_honors_empty_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            data, _source, evidence_path = self._conditional_rough_project(directory)
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["items"][0]["raw_failures"] = ["audio.long_silence"]
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            mismatch = AgentCutEngine().validate(data)
            self.assertFalse(mismatch.valid)
            self.assertIn(
                "conditional_raw_review_failures_mismatch",
                mismatch.coverage["sourceAdmission"]["items"][0]["reasons"],
            )

        with tempfile.TemporaryDirectory() as directory:
            data, _source, _evidence = self._conditional_rough_project(directory)
            data["sourceAdmissionPolicy"]["allowedConditionalFailureCodes"] = []
            denied = AgentCutEngine().validate(data)
            self.assertFalse(denied.valid)
            self.assertIn(
                "conditional_failure_not_rough_eligible:video.periodic_duplicate",
                denied.coverage["sourceAdmission"]["items"][0]["reasons"],
            )

    def test_conditional_sources_and_hold_slots_can_never_pass_release_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            data, _source, _evidence = self._conditional_rough_project(directory)
            final = Path(directory) / "review-target.mp4"
            final.write_bytes(b"immutable rough assembly bytes")
            final_sha = hashlib.sha256(final.read_bytes()).hexdigest()
            review = {
                "schema": "qingshan.review.report.v2", "scope": "full_cut", "media_kind": "video",
                "media_sha256": final_sha, "hard_gate_passed": True,
            }
            result = AgentCutEngine().validate_release(final, review, project=data)
            self.assertFalse(result["cleanRelease"])
            self.assertIn("RELEASE_CONDITIONAL_SOURCES_UNRESOLVED", result["failures"])
            self.assertIn("RELEASE_UNRESOLVED_HOLD_SLOTS", result["failures"])
            self.assertFalse(result["platformMutationAuthorized"])

    def test_final_visual_gate_cannot_promote_conditional_sources_or_hold_slots(self):
        with tempfile.TemporaryDirectory() as directory:
            data, _source, _evidence = self._conditional_rough_project(directory)
            with patch("agentcut.engine.FinalVisualValidator.analyze", return_value={
                "status": "PASS", "hardGatePassed": True, "violations": [],
                "platformMutationAuthorized": False,
            }):
                result = AgentCutEngine().validate_final_visual(Path(directory) / "rough.mp4", project=data)
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse(result["hardGatePassed"])
            codes = {item["code"] for item in result["releaseBlockers"]}
            self.assertEqual(codes, {
                "FINAL_VISUAL_CONDITIONAL_SOURCES_UNRESOLVED",
                "FINAL_VISUAL_HOLD_SLOTS_UNRESOLVED",
            })

    def test_hold_slots_reject_standard_mode_and_visible_video_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            data, _source, _evidence = self._conditional_rough_project(directory)
            data["assemblyMode"] = "STANDARD"
            data["timeline"]["holdSlots"][0]["start"] = 1
            report = AgentCutEngine().validate(data)
            codes = {issue.code for issue in report.issues}
            self.assertIn("HOLD_SLOT_REQUIRES_ROUGH_ASSEMBLY", codes)
            self.assertIn("HOLD_SLOT_OVERLAPS_VIDEO", codes)
            self.assertFalse(report.valid)

    @unittest.skipUnless(E28_CL2X517_PROJECT.is_file(), "E28 CL2X-517 production project unavailable")
    def test_e28_cl2x517_real_project_preserves_raw_failures_and_resolves_hold_gap(self):
        report = AgentCutEngine().validate(self.E28_CL2X517_PROJECT, strict_media=True)
        self.assertTrue(report.valid, [issue.to_dict() for issue in report.issues])
        source = report.coverage["sourceAdmission"]
        self.assertEqual(source["status"], "PASS_NON_RELEASE_ROUGH_ASSEMBLY")
        self.assertEqual(source["conditionallyAdmittedCount"], 4)
        by_shot = {item["shotId"]: item for item in source["items"]}
        for unit in ("E28-CW-U02", "E28-CW-U03", "E28-CW-U11"):
            self.assertEqual(by_shot[unit]["cadenceStatus"], "FAIL")
            self.assertIn("video.periodic_duplicate", by_shot[unit]["conditionalEvidence"]["rawFailures"])
        self.assertEqual(report.coverage["holdSlots"]["items"][0]["id"], "E28-CW-U09")
        self.assertEqual(report.coverage["finalVideoGaps"], [])

    @unittest.skipUnless(E27_N09_CADENCE.is_file() and E27_N04_CADENCE.is_file() and E27_N19_CADENCE.is_file(), "E27 production evidence unavailable")
    def test_e27_n09_n04_block_and_n19_pass_per_shot_admission(self):
        n09 = self._admission_project("E27-N09", self.E27_N09_CADENCE, admission="CONDITIONAL_MACHINE_ADMISSION")
        n09_report = AgentCutEngine().validate(n09)
        self.assertFalse(n09_report.valid)
        self.assertIn("action_near_duplicate_ratio_exceeded", n09_report.coverage["sourceAdmission"]["items"][0]["reasons"][0])
        self.assertAlmostEqual(n09_report.coverage["sourceAdmission"]["items"][0]["nearDuplicateRatio"], 0.15104166666666666)
        with self.assertRaisesRegex(ValidationError, "BLOCK_AGENTCUT_ASSEMBLY"):
            AgentCutEngine().compile(n09)
        with self.assertRaisesRegex(ValidationError, "BLOCK_AGENTCUT_ASSEMBLY"):
            AgentCutEngine().render(n09)

        n04 = self._admission_project(
            "E27-N04", self.E27_N04_CADENCE,
            reference_mode="single_still_only", admission="CONDITIONAL_MACHINE_ADMISSION",
        )
        n04_report = AgentCutEngine().validate(n04)
        self.assertFalse(n04_report.valid)
        self.assertIn("single_still_only_cannot_prove_required_action", n04_report.coverage["sourceAdmission"]["items"][0]["reasons"])

        n19 = self._admission_project("E27-N19", self.E27_N19_CADENCE)
        n19_report = AgentCutEngine().validate(n19)
        self.assertTrue(n19_report.valid, [issue.to_dict() for issue in n19_report.issues])
        self.assertAlmostEqual(n19_report.coverage["sourceAdmission"]["items"][0]["nearDuplicateRatio"], 0.020833333333333332)
        self.assertEqual(n19_report.coverage["sourceAdmission"]["status"], "PASS")
        self.assertIn("ffmpeg", AgentCutEngine().compile(n19).argv[0])

    def test_action_required_metadata_contract_is_strict(self):
        data = project()
        metadata = data["timeline"]["videoTracks"][0]["clips"][0].setdefault("metadata", {})
        metadata.update({"action_required": "yes", "source_reference_mode": "single_still_only"})
        with self.assertRaisesRegex(ValidationError, "action_required must be a boolean"):
            AgentCutEngine().load(data)
        metadata["action_required"] = True
        metadata["action_trajectory"] = {"windup": "only one stage"}
        report = AgentCutEngine().validate(data)
        self.assertFalse(report.valid)
        self.assertIn("BLOCK_AGENTCUT_ASSEMBLY", {issue.code for issue in report.issues})

    def test_release_gate_requires_exact_current_sha_and_hard_gate(self):
        engine = AgentCutEngine()
        with tempfile.TemporaryDirectory() as directory:
            final = Path(directory) / "final.mp4"
            final.write_bytes(b"current immutable final bytes")
            digest = hashlib.sha256(final.read_bytes()).hexdigest()
            review = Path(directory) / "review.json"
            review.write_text(json.dumps({
                "schema": "qingshan.review.report.v2", "scope": "final",
                "media_kind": "video",
                "media_sha256": digest, "scoring": {"hard_gate_passed": True},
            }), encoding="utf-8")
            passed = engine.validate_release(final, review)
            self.assertTrue(passed["cleanRelease"])
            self.assertTrue(passed["shaMatches"])
            self.assertFalse(passed["automaticPlatformReplacementAllowed"])
            self.assertFalse(passed["platformMutationAuthorized"])

            final.write_bytes(b"changed final bytes")
            failed = engine.validate_release(final, review)
            self.assertFalse(failed["cleanRelease"])
            self.assertIn("RELEASE_REVIEW_FINAL_SHA_MISMATCH", failed["failures"])

    def test_ndjson_release_validation_never_authorizes_platform_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            final = Path(directory) / "final.mp4"
            final.write_bytes(b"final")
            digest = hashlib.sha256(final.read_bytes()).hexdigest()
            review = {"schema": "qingshan.review.report.v2", "scope": "full_cut", "media_kind": "video",
                      "media_sha256": digest, "hard_gate_passed": True}
            response = AgentServer(AgentCutEngine(), workers=1).handle({
                "id": "release", "method": "validateRelease", "params": {"final": str(final), "review": review},
            })
            self.assertTrue(response["result"]["cleanRelease"])
            self.assertFalse(response["result"]["conditionalMachineAdmissionTriggersPlatformReplacement"])
            self.assertFalse(response["result"]["platformMutationAuthorized"])

    def test_render_manifest_keeps_release_pending_until_current_sha_review(self):
        engine = AgentCutEngine()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            output = Path(directory) / "candidate.mp4"
            made = subprocess.run([
                engine.ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x568:r=24:d=1",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source),
            ], capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            cadence = Path(directory) / "cadence.json"
            cadence.write_text(json.dumps({
                "status": "PASS", "video": str(source),
                "periodic_duplicates": {"near_duplicate_ratio": 0.01},
            }), encoding="utf-8")
            data = {
                "version": "1.0", "output": {"path": str(output), "width": 320, "height": 568, "fps": 24},
                "sourceAdmissionPolicy": {"enabled": True}, "releaseGate": {"required": True},
                "timeline": {"videoTracks": [{"id": "Video.Main", "clips": [{
                    "id": "ACTION", "source": str(source), "duration": 1,
                    "metadata": {
                        "action_required": True,
                        "action_trajectory": {"windup": "raise", "contact": "touch", "force": "push", "result": "opens"},
                        "source_reference_mode": "generated_video", "cadence_report_path": str(cadence),
                        "source_admission": "PASS",
                    },
                }]}]},
            }
            rendered = engine.render(data)
            self.assertEqual(rendered.manifest["sourceAdmission"]["status"], "PASS")
            self.assertEqual(rendered.manifest["releaseGate"]["status"], "PENDING_POST_RENDER_VISUAL_REVIEW")
            self.assertFalse(rendered.manifest["releaseGate"]["cleanRelease"])
            self.assertFalse(rendered.manifest["releaseGate"]["automaticPlatformReplacementAllowed"])
    def test_dialogue_isolation_confidence_is_conservative(self):
        self.assertEqual(isolation_confidence(-20, -20), 0.125)
        self.assertLess(isolation_confidence(-20, -15), 0.8)
        self.assertLess(isolation_confidence(-10, -25), 0.8)

    def test_audio_save_health_performs_real_write_and_selects_fallback(self):
        engine = AgentCutEngine()
        health = audio_save_health(engine.ffmpeg)
        self.assertTrue(health["ready"])
        self.assertIn(health["selectedBackend"], {"soundfile", "ffmpeg", "torchaudio"})
        self.assertEqual(health["probe"], "actual WAV write")
        self.assertTrue(health["failFastBeforeModelLoad"])

    def test_audio_save_backend_fails_before_model_work(self):
        unavailable = {"ready": False, "selectedBackend": None, "backends": {"soundfile": {"available": False, "error": "missing"}}}
        with patch("agentcut.audio_backend.audio_save_health", return_value=unavailable):
            with self.assertRaisesRegex(Exception, "refusing model download/inference"):
                require_audio_save_backend("ffmpeg")

    def test_nalu_outro_is_appended_and_manifested_by_compiler(self):
        data = project()
        data["output"].update({"width": 720, "height": 1280})
        data["outro"] = {"enabled": True}
        compiled = AgentCutEngine().compile(data)
        self.assertEqual(compiled.summary["outro"]["present"], True)
        self.assertEqual(compiled.summary["outro"]["actualStart"], 5.25)
        self.assertEqual(compiled.summary["outro"]["actualEnd"], 8.25)
        self.assertIn("[vwithoutro]", compiled.filter_graph)
        self.assertIn("NALU MOTION", compiled.filter_graph)
        self.assertIn("[amain][aoutro]concat", compiled.filter_graph)

    def test_nalu_outro_hard_gates_missing_asset_and_safe_area(self):
        data = project()
        data["output"].update({"width": 720, "height": 1280})
        data["outro"] = {"enabled": True, "assetPath": "/definitely/missing/nalu.png",
                         "logo": {"x": 0, "y": 0, "width": 700, "height": 1200}}
        report = AgentCutEngine().validate(data)
        codes = {issue.code for issue in report.issues}
        self.assertIn("OUTRO_ASSET_MISSING", codes)
        self.assertIn("OUTRO_SAFE_AREA_OVERFLOW", codes)
        self.assertFalse(report.valid)

    def test_old_project_has_no_outro_and_keeps_duration(self):
        parsed = AgentCutEngine().load(project())
        self.assertFalse(parsed.outro.enabled)
        self.assertEqual(parsed.duration, parsed.main_duration)

    def test_require_branded_outro_is_strict_hard_gate(self):
        data = project()
        data["requireBrandedOutro"] = True
        report = AgentCutEngine().validate(data)
        self.assertFalse(report.valid)
        self.assertIn("BRANDED_OUTRO_REQUIRED", {x.code for x in report.issues})
        self.assertEqual(report.coverage["outro"], {"present": False, "enabled": False, "brand": None,
                                                    "duration": 0, "endsAtTimelineEnd": False, "required": True})

    def test_branded_outro_rejects_wrong_brand_start_and_crop(self):
        data = project()
        data["output"].update({"width": 720, "height": 1280})
        data["requireBrandedOutro"] = True
        data["outro"] = {"enabled": True, "brand": "generic", "start": 4, "fit": "cover"}
        report = AgentCutEngine().validate(data)
        codes = {x.code for x in report.issues}
        self.assertTrue({"OUTRO_BRAND_INVALID", "OUTRO_NOT_AT_TIMELINE_END", "OUTRO_BRAND_CROP_RISK"}.issubset(codes))

    def test_nalu_outro_asset_can_be_injected_by_environment(self):
        data = project()
        data["output"].update({"width": 720, "height": 1280})
        data["requireBrandedOutro"] = True
        data["outro"] = {"enabled": True, "brand": "nalu_motion", "fit": "contain"}
        with patch.dict("os.environ", {"AGENTCUT_NALU_MOTION_OUTRO_ASSET": CHINESE_FONT}):
            parsed = AgentCutEngine().load(data)
        self.assertEqual(parsed.outro.asset_path, CHINESE_FONT)

    def test_ndjson_validate_returns_branded_outro_coverage(self):
        data = project()
        data["output"].update({"width": 720, "height": 1280})
        data["requireBrandedOutro"] = True
        data["outro"] = {"enabled": True, "brand": "nalu_motion", "fit": "contain"}
        response = AgentServer(AgentCutEngine(), workers=1).handle({"id": "outro", "method": "validate", "params": {"project": data}})
        coverage = response["result"]["coverage"]["outro"]
        self.assertTrue(coverage["present"])
        self.assertEqual(coverage["brand"], "nalu_motion")
        self.assertTrue(coverage["endsAtTimelineEnd"])

    def test_cleanup_regions_compile_before_burned_captions(self):
        data = subtitled_project()
        data["output"].update({"width": 720, "height": 1280})
        data["timeline"]["videoTracks"][0]["clips"][0]["cleanupRegions"] = [
            {"mode": "delogo", "x": 250, "y": 850, "width": 230, "height": 110, "start": 0.2, "duration": 1.5}
        ]
        compiled = AgentCutEngine().compile(data)
        self.assertIn("delogo=x=250:y=850:w=230:h=110", compiled.filter_graph)
        self.assertLess(compiled.filter_graph.index("delogo=x=250"), compiled.filter_graph.index("drawtext=text='半夜送礼'"))
        self.assertEqual(compiled.summary["clips"][0]["cleanupRegions"][0]["mode"], "delogo")

    def test_cleanup_region_caption_safe_band_is_hard_gate(self):
        data = subtitled_project()
        data["output"].update({"width": 720, "height": 1280})
        data["timeline"]["videoTracks"][0]["clips"][0]["cleanupRegions"] = [
            {"mode": "mask", "x": 100, "y": 1080, "width": 300, "height": 80, "duration": 1}
        ]
        report = AgentCutEngine().validate(data)
        self.assertIn("CLEANUP_CAPTION_SAFE_BAND_OVERLAP", {x.code for x in report.issues})
        data["timeline"]["videoTracks"][0]["clips"][0]["cleanupRegions"][0]["allowCaptionSafeBand"] = True
        report = AgentCutEngine().validate(data)
        self.assertNotIn("CLEANUP_CAPTION_SAFE_BAND_OVERLAP", {x.code for x in report.issues})

    def test_cleanup_region_bounds_and_time_are_rejected(self):
        data = project()
        data["timeline"]["videoTracks"][0]["clips"][0]["cleanupRegions"] = [
            {"mode": "blur", "x": 1200, "y": 600, "width": 200, "height": 100, "duration": 1}
        ]
        report = AgentCutEngine().validate(data)
        self.assertIn("CLEANUP_REGION_OUT_OF_BOUNDS", {x.code for x in report.issues})
        data["timeline"]["videoTracks"][0]["clips"][0]["cleanupRegions"][0].update({"x": 10, "start": 3.5, "duration": 1})
        with self.assertRaisesRegex(ValidationError, "cleanup time exceeds clip duration"):
            AgentCutEngine().load(data)

    def test_ndjson_compile_supports_cleanup_regions(self):
        data = project()
        data["timeline"]["videoTracks"][0]["clips"][0]["cleanupRegions"] = [
            {"mode": "mask", "x": 10, "y": 10, "width": 100, "height": 40, "duration": 1}
        ]
        response = AgentServer(AgentCutEngine(), workers=1).handle({"id": "cleanup", "method": "compile", "params": {"project": data}})
        self.assertTrue(response["ok"])
        self.assertIn("drawbox=x=10:y=10:w=100:h=40", response["result"]["filterGraph"])

    def test_release_project_requires_master_audio_policy(self):
        data = project()
        data["releaseProject"] = True
        report = AgentCutEngine().validate(data)
        self.assertFalse(report.valid)
        codes = {x.code for x in report.issues}
        self.assertIn("MASTER_AUDIO_POLICY_REQUIRED", codes)
        self.assertTrue({
            "RELEASE_SUBTITLES_REQUIRED", "RELEASE_DIALOGUE_IDS_REQUIRED",
            "RELEASE_OUTRO_REQUIRED", "RELEASE_OUTRO_ENABLED_REQUIRED",
            "RELEASE_VISUAL_GATE_REQUIRED",
        }.issubset(codes))
        self.assertEqual(report.coverage["releaseProjectContract"]["status"], "FAIL")

    def test_complete_release_project_contract_passes(self):
        data = subtitled_project()
        data["releaseProject"] = True
        data["requireBrandedOutro"] = True
        data["outro"] = {"enabled": True}
        data["releaseGate"] = {"required": True}
        parsed = AgentCutEngine().load(data)
        issues, coverage = validate_release_project_contract(parsed)
        self.assertEqual(issues, [])
        self.assertEqual(coverage["status"], "PASS")

    def test_compile_fails_before_render_when_release_contract_is_incomplete(self):
        data = project()
        data["releaseProject"] = True
        with self.assertRaisesRegex(ValidationError, "RELEASE_SUBTITLES_REQUIRED"):
            AgentCutEngine().compile(data)

    def test_replacement_binding_gate_accepts_exact_new_source(self):
        with tempfile.TemporaryDirectory() as directory:
            replacement = Path(directory) / "fixed.mp4"
            replacement.write_bytes(b"admitted replacement")
            digest = hashlib.sha256(replacement.read_bytes()).hexdigest()
            data = project()
            clip = data["timeline"]["videoTracks"][0]["clips"][0]
            clip.update({"id": "U03-S1-A", "source": str(replacement), "metadata": {"source_sha256": digest}})
            data["metadata"] = {"replacementBindingPolicy": {
                "enabled": True, "expectedTargetCount": 1,
                "targets": [{"clipId": "U03-S1-A", "replacementSourceSha256": digest}],
                "forbiddenPathTokens": ["SMOOTH_ROAM"],
            }}
            issues, coverage = validate_replacement_bindings(AgentCutEngine().load(data))
            self.assertEqual(issues, [])
            self.assertEqual(coverage["status"], "PASS")
            self.assertEqual(coverage["matched"], 1)

    def test_replacement_binding_gate_blocks_stale_project_path(self):
        with tempfile.TemporaryDirectory() as directory:
            replacement = Path(directory) / "fixed.mp4"
            replacement.write_bytes(b"admitted replacement")
            stale = Path(directory) / "U03_SMOOTH_ROAM_old.mp4"
            stale.write_bytes(b"old moving source")
            digest = hashlib.sha256(replacement.read_bytes()).hexdigest()
            stale_digest = hashlib.sha256(stale.read_bytes()).hexdigest()
            data = project()
            clip = data["timeline"]["videoTracks"][0]["clips"][0]
            clip.update({"id": "U03-S1-A", "source": str(stale), "metadata": {"source_sha256": stale_digest}})
            data["metadata"] = {"replacementBindingPolicy": {
                "enabled": True, "expectedTargetCount": 1,
                "targets": [{"clipId": "U03-S1-A", "replacementSourceSha256": digest}],
                "forbiddenSourceSha256": [stale_digest], "forbiddenPathTokens": ["SMOOTH_ROAM"],
            }}
            parsed = AgentCutEngine().load(data)
            issues, coverage = validate_replacement_bindings(parsed)
            codes = {issue.code for issue in issues}
            self.assertIn("REPLACEMENT_BINDING_SHA_MISMATCH", codes)
            self.assertIn("SUPERSEDED_SOURCE_STILL_BOUND", codes)
            self.assertEqual(coverage["status"], "FAIL")
            with self.assertRaisesRegex(ValidationError, "REPLACEMENT_BINDING_SHA_MISMATCH"):
                AgentCutEngine().compile(data)

    def test_replacement_binding_gate_blocks_incomplete_target_coverage(self):
        data = project()
        data["metadata"] = {"replacementBindingPolicy": {
            "enabled": True, "expectedTargetCount": 2,
            "targets": [{"clipId": "missing", "replacementSourceSha256": "a" * 64}],
        }}
        issues, coverage = validate_replacement_bindings(AgentCutEngine().load(data))
        self.assertIn("REPLACEMENT_BINDING_COVERAGE_INCOMPLETE", {issue.code for issue in issues})
        self.assertIn("REPLACEMENT_BINDING_TARGET_MISSING", {issue.code for issue in issues})
        self.assertEqual(coverage["expected"], 2)

    def test_release_repair_cannot_omit_replacement_binding_policy(self):
        data = project()
        data["releaseProject"] = True
        clip = data["timeline"]["videoTracks"][0]["clips"][0]
        clip["id"] = "repaired-clip"
        clip["metadata"] = {"original_source": "old.mp4", "source_sha256": "a" * 64}
        issues, coverage = validate_replacement_bindings(AgentCutEngine().load(data))
        self.assertIn("REPLACEMENT_BINDING_POLICY_REQUIRED", {issue.code for issue in issues})
        self.assertEqual(coverage["status"], "FAIL")

    def test_render_fails_before_media_work_when_release_contract_is_incomplete(self):
        data = project()
        data["releaseProject"] = True
        data["timeline"]["audioTracks"] = []
        with self.assertRaisesRegex(ValidationError, "RELEASE_SUBTITLES_REQUIRED"):
            AgentCutEngine().render(data)

    def test_release_output_name_also_requires_master_audio_policy(self):
        data = project()
        data["output"]["path"] = "E19R_RELEASE_CANDIDATE.mp4"
        measured = Mock(returncode=0, stderr="[Parsed_volumedetect] max_volume: -0.9 dB\n")
        with patch("agentcut.validation.subprocess.run", return_value=measured):
            report = AgentCutEngine().validate(data)
        self.assertIn("MASTER_AUDIO_POLICY_REQUIRED", {x.code for x in report.issues})

    def test_projected_gain_includes_source_volume_and_overlap_headroom(self):
        data = project()
        data["masterAudioPolicy"] = {"required": True, "limiter": True, "truePeakCeilingDbtp": -1,
                                     "loudnessTargetLufs": -16, "maxClippedSamples": 0}
        data["timeline"]["audioTracks"][0]["clips"][0]["volume"] = 5.5
        data["timeline"]["audioTracks"][0]["clips"].append({"source": "v.wav", "start": .25, "duration": 5, "volume": 5.5})
        measured = Mock(returncode=0, stderr="[Parsed_volumedetect] max_volume: -0.9 dB\n")
        with patch("agentcut.validation.subprocess.run", return_value=measured):
            report = AgentCutEngine().validate(data)
        risk = report.coverage["audioSafety"]["projected"]
        self.assertTrue(risk["risk"])
        self.assertGreater(risk["worstCombinedPeakDbfs"], 19)
        issue = next(x for x in report.issues if x.code == "PROJECTED_AUDIO_CLIPPING_RISK")
        self.assertEqual(issue.severity, "warning")
        self.assertTrue(report.valid)

    def test_master_audio_policy_compiles_loudnorm_true_peak_ceiling(self):
        data = project()
        data["masterAudioPolicy"] = {"required": True, "limiter": True, "truePeakCeilingDbtp": -1,
                                     "loudnessTargetLufs": -16, "loudnessRangeLu": 11}
        graph = AgentCutEngine().compile(data).filter_graph
        self.assertIn("loudnorm=I=-16:TP=-1.5:LRA=11", graph)
        self.assertIn("[apremaster]", graph)
        summary = AgentCutEngine().compile(data).summary
        self.assertTrue(summary["renderUsesMeasuredTwoPass"])
        self.assertEqual(summary["renderPlan"], {"audioMastering": "measured-two-pass", "atomicOutput": True})

    def test_aac_codec_headroom_survives_postflight_exact_ceiling(self):
        engine = AgentCutEngine()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "hot.mkv"
            output = Path(directory) / "AAC_RELEASE_CANDIDATE.mp4"
            made = subprocess.run([
                engine.ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=720x1280:r=30:d=2",
                "-f", "lavfi", "-i", "sine=f=997:r=48000:d=2", "-filter:a", "volume=17dB", "-shortest",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "pcm_s24le", "-y", str(source),
            ], capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            data = {
                "version": "1.0",
                "masterAudioPolicy": {"required": True, "limiter": True, "truePeakCeilingDbtp": -1,
                                      "codecHeadroomDb": .5, "loudnessTargetLufs": -16, "maxClippedSamples": 0},
                "output": {"path": str(output), "width": 720, "height": 1280},
                "timeline": {
                    "videoTracks": [{"id": "main", "clips": [{"source": str(source), "duration": 2}]}],
                    "audioTracks": [{"id": "dialogue", "clips": [
                        {"source": str(source), "duration": 2, "volume": 5.5},
                        {"source": str(source), "duration": 2, "volume": 5.5},
                    ]}],
                },
            }
            stale_report = Path(str(output) + ".failed-audio-qa.json")
            stale_report.write_text('{"stale":true}\n')
            rendered = engine.render(data, overwrite=True)
            metrics = rendered.manifest["audioSafety"]["metrics"]
            self.assertLessEqual(metrics["truePeakDbtp"], -1.0)
            self.assertLessEqual(abs(metrics["integratedLoudnessLufs"] - (-16)), 1.0)
            self.assertEqual(metrics["clippedSampleCount"], 0)
            mastering = rendered.manifest["audioSafety"]["mastering"]
            self.assertEqual(mastering["mode"], "measured-two-pass")
            self.assertIsNotNone(mastering["measurement"])
            self.assertIn("measured_I=", mastering["filter"])
            self.assertTrue(output.exists())
            self.assertFalse(stale_report.exists())

    def test_failed_master_gate_preserves_existing_output_atomically(self):
        engine = AgentCutEngine()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "quiet.mkv"
            output = Path(directory) / "ATOMIC_RELEASE_CANDIDATE.mp4"
            made = subprocess.run([
                engine.ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x568:r=24:d=1",
                "-f", "lavfi", "-i", "sine=f=440:r=48000:d=1", "-shortest",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "pcm_s24le", "-y", str(source),
            ], capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            sentinel = b"existing-published-output-must-survive"
            output.write_bytes(sentinel)
            data = {
                "version": "1.0",
                "masterAudioPolicy": {"required": True, "limiter": True, "truePeakCeilingDbtp": -9,
                                      "codecHeadroomDb": 0, "loudnessTargetLufs": -5, "maxClippedSamples": 0},
                "output": {"path": str(output), "width": 320, "height": 568, "fps": 24},
                "timeline": {
                    "videoTracks": [{"id": "main", "clips": [{"source": str(source), "duration": 1}]}],
                    "audioTracks": [{"id": "dialogue", "clips": [{"source": str(source), "duration": 1}]}],
                },
            }
            with self.assertRaisesRegex(AgentCutError, "master audio safety gate failed"):
                engine.render(data, overwrite=True)
            self.assertEqual(output.read_bytes(), sentinel)
            report = json.loads(Path(str(output) + ".failed-audio-qa.json").read_text())
            self.assertFalse(report["outputPublished"])
            self.assertTrue(report["stagedOutputRemoved"])
            self.assertTrue(report["existingOutputPreserved"])
            self.assertEqual(list(Path(directory).glob(".*.agentcut-candidate.*")), [])
            self.assertEqual(list(Path(directory).glob(".*.agentcut-premaster.mkv")), [])

    def test_compile_burns_chinese_captions_in_9x16_safe_area(self):
        data = subtitled_project()
        data["output"].update({"width": 720, "height": 1280})
        compiled = AgentCutEngine().compile(data)
        self.assertIn("drawtext=text='半夜送礼'", compiled.filter_graph)
        self.assertIn(f"fontfile='{CHINESE_FONT}'", compiled.filter_graph)
        self.assertIn("y=h-text_h-160", compiled.filter_graph)
        self.assertEqual(compiled.summary["subtitleTracks"], 1)
        self.assertEqual(len(compiled.summary["captions"]), 2)

    def test_wrapped_caption_uses_independent_line_layers_without_newline_escape(self):
        data = subtitled_project()
        data["timeline"]["subtitleTracks"][0]["style"]["wrap"] = 4
        data["timeline"]["subtitleTracks"][0]["clips"][0]["text"] = "半夜送礼请勿声张"
        compiled = AgentCutEngine().compile(data)
        self.assertIn("drawtext=text='半夜送礼'", compiled.filter_graph)
        self.assertIn("drawtext=text='请勿声张'", compiled.filter_graph)
        self.assertNotIn("\\n", compiled.filter_graph)
        self.assertIn("y=h-text_h-160-53", compiled.filter_graph)
        self.assertIn("y=h-text_h-160-0", compiled.filter_graph)

    def test_wrapped_caption_never_orphans_closing_punctuation(self):
        data = subtitled_project()
        data["timeline"]["subtitleTracks"][0]["style"]["wrap"] = 4
        data["timeline"]["subtitleTracks"][0]["clips"][0]["text"] = "半夜送礼，请勿声张。"
        compiled = AgentCutEngine().compile(data)
        self.assertIn("drawtext=text='半夜送礼，'", compiled.filter_graph)
        self.assertIn("drawtext=text='请勿声'", compiled.filter_graph)
        self.assertIn("drawtext=text='张。'", compiled.filter_graph)
        self.assertNotIn("drawtext=text='，", compiled.filter_graph)
        self.assertNotIn("drawtext=text='。", compiled.filter_graph)

    def test_wrapped_caption_keeps_opening_quote_with_following_text(self):
        data = subtitled_project()
        data["timeline"]["subtitleTracks"][0]["style"]["wrap"] = 5
        data["timeline"]["subtitleTracks"][0]["clips"][0]["text"] = "该看见的人，‘不小心’看见。"
        compiled = AgentCutEngine().compile(data)
        self.assertNotIn("人，‘'", compiled.filter_graph)
        self.assertIn("drawtext=text='‘不小心’", compiled.filter_graph)

    def test_required_subtitle_track_is_a_hard_gate_without_strict_media(self):
        data = project()
        data["requireBurnedSubtitles"] = True
        report = AgentCutEngine().validate(data)
        self.assertFalse(report.valid)
        self.assertIn("SUBTITLE_TRACK_REQUIRED", {x.code for x in report.issues})

    def test_subtitle_coverage_is_one_to_one(self):
        report = AgentCutEngine().validate(subtitled_project())
        self.assertTrue(report.valid, [x.to_dict() for x in report.issues])
        coverage = report.coverage["subtitles"]
        self.assertEqual(coverage["count"], "2/2")
        self.assertEqual(coverage["matchedDialogueIds"], ["D1", "D2"])

    def test_subtitle_coverage_reports_40_of_40(self):
        data = project()
        ids = [f"DIA-{i:03d}" for i in range(1, 41)]
        data["requireBurnedSubtitles"] = True
        data["expectedDialogueIds"] = ids
        data["timeline"]["subtitleTracks"] = [{
            "id": "zh-CN", "style": {"font": CHINESE_FONT},
            "clips": [{"dialogue_id": dialogue_id, "text": "字幕", "start": i * .1, "duration": .09} for i, dialogue_id in enumerate(ids)],
        }]
        report = AgentCutEngine().validate(data)
        self.assertTrue(report.valid, [x.to_dict() for x in report.issues])
        self.assertEqual(report.coverage["subtitles"]["count"], "40/40")

    def test_subtitle_validation_rejects_missing_glyph(self):
        data = subtitled_project()
        data["timeline"]["subtitleTracks"][0]["clips"][0]["text"] = "😀"
        report = AgentCutEngine().validate(data)
        self.assertIn("SUBTITLE_GLYPH_MISSING", {x.code for x in report.issues})

    def test_subtitle_validation_rejects_empty_overlap_bounds_id_font_and_glyphs(self):
        data = subtitled_project()
        clips = data["timeline"]["subtitleTracks"][0]["clips"]
        clips[0].update({"text": "", "dialogue_id": None, "duration": 4})
        clips[1].update({"start": 1, "duration": 20, "font": "/missing/font.ttf"})
        report = AgentCutEngine().validate(data)
        codes = {x.code for x in report.issues}
        self.assertTrue({"SUBTITLE_EMPTY_TEXT", "SUBTITLE_DIALOGUE_ID_REQUIRED", "SUBTITLE_OVERLAP", "SUBTITLE_OUT_OF_BOUNDS", "SUBTITLE_FONT_MISSING"}.issubset(codes))

    def test_render_preflight_rejects_missing_required_subtitles(self):
        data = project()
        data["requireBurnedSubtitles"] = True
        with self.assertRaisesRegex(ValidationError, "SUBTITLE_TRACK_REQUIRED"):
            AgentCutEngine().render(data, overwrite=True)

    def test_ndjson_validate_reports_subtitle_coverage(self):
        response = AgentServer(AgentCutEngine(), workers=1).handle({
            "id": "subs", "method": "validate", "params": {"project": subtitled_project()}
        })
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["coverage"]["subtitles"]["count"], "2/2")

    def test_compile_builds_timed_video_and_audio(self):
        result = AgentCutEngine().compile(project())
        self.assertIn("trim=start=2:duration=4", result.filter_graph)
        self.assertIn("setpts=PTS+30/(30*TB)", result.filter_graph)
        self.assertIn("anullsrc=r=48000:cl=stereo:d=0.25", result.filter_graph)
        self.assertIn("concat=n=2:v=0:a=1", result.filter_graph)
        self.assertIn("volume=0.8", result.filter_graph)
        self.assertEqual(result.argv[-1], "out.mp4")

    def test_compile_deduplicates_repeated_sources_and_splits_stream(self):
        data = project()
        data["timeline"]["videoTracks"][0]["clips"].append({
            "source": "a.mp4", "start": 5, "in": 0, "duration": 1,
        })
        result = AgentCutEngine().compile(data)
        self.assertEqual(result.argv.count("a.mp4"), 1)
        self.assertEqual(result.summary["inputCount"], 2)
        self.assertIn("[0:v]split=2", result.filter_graph)

    def test_non_frame_aligned_hard_cut_has_no_isolated_black_frame(self):
        engine = AgentCutEngine()
        with tempfile.TemporaryDirectory() as directory:
            red = Path(directory) / "red.mp4"
            blue = Path(directory) / "blue.mp4"
            output = Path(directory) / "hard-cut.mp4"
            for color, destination in (("red", red), ("blue", blue)):
                made = subprocess.run([
                    engine.ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                    f"color=c={color}:s=320x568:r=24:d=0.25",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(destination),
                ], capture_output=True, text=True)
                self.assertEqual(made.returncode, 0, made.stderr)
            data = {
                "version": "1.0",
                "output": {"path": str(output), "width": 320, "height": 568, "fps": 24},
                "timeline": {"videoTracks": [{"id": "main", "clips": [
                    {"id": "red", "source": str(red), "start": 0, "duration": 0.26},
                    {"id": "blue", "source": str(blue), "start": 0.26, "duration": 0.24},
                ]}]},
            }
            compiled = engine.compile(data)
            ranges = [item["visualFrameRange"] for item in compiled.summary["clips"]]
            self.assertEqual(ranges[0]["endFrameExclusive"], 6)
            self.assertEqual(ranges[1]["startFrame"], 6)
            self.assertIn("tpad=stop_mode=clone:stop_duration=0.041666666667", compiled.filter_graph)
            self.assertIn("eof_action=pass:repeatlast=0", compiled.filter_graph)
            self.assertIn("setpts=PTS+6/(24*TB)", compiled.filter_graph)
            engine.render(data, overwrite=True)
            black_scan = subprocess.run([
                engine.ffmpeg, "-hide_banner", "-i", str(output),
                "-vf", "blackframe=amount=95:threshold=32", "-an", "-f", "null", "-",
            ], capture_output=True, text=True)
            self.assertEqual(black_scan.returncode, 0, black_scan.stderr)
            self.assertNotIn("Parsed_blackframe", black_scan.stderr)

    def test_hard_cut_does_not_clone_or_repeat_source_tail(self):
        engine = AgentCutEngine()
        with tempfile.TemporaryDirectory() as directory:
            moving = Path(directory) / "moving.mp4"
            next_clip = Path(directory) / "next.mp4"
            output = Path(directory) / "cadence.mp4"
            made = subprocess.run([
                engine.ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=s=320x568:r=24:d=0.5", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-y", str(moving),
            ], capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            made = subprocess.run([
                engine.ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                "color=c=blue:s=320x568:r=24:d=0.25", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-y", str(next_clip),
            ], capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            data = {
                "version": "1.0",
                "output": {"path": str(output), "width": 320, "height": 568, "fps": 24},
                "timeline": {"videoTracks": [{"id": "main", "clips": [
                    {"id": "moving", "source": str(moving), "start": 0, "duration": 0.49},
                    {"id": "next", "source": str(next_clip), "start": 0.49, "duration": 0.26},
                ]}]},
            }
            compiled = engine.compile(data)
            self.assertIn("tpad=stop_mode=clone:stop_duration=0.041666666667", compiled.filter_graph)
            self.assertNotIn("eof_action=repeat", compiled.filter_graph)
            engine.render(data, overwrite=True)
            hashes = subprocess.run([
                engine.ffmpeg, "-v", "error", "-i", str(output),
                "-vf", "select=between(n\\,8\\,11)", "-an", "-f", "framemd5", "-",
            ], capture_output=True, text=True)
            self.assertEqual(hashes.returncode, 0, hashes.stderr)
            frame_hashes = [line.rsplit(",", 1)[-1].strip() for line in hashes.stdout.splitlines()
                            if line and not line.startswith("#")]
            self.assertEqual(len(frame_hashes), 4)
            self.assertEqual(len(set(frame_hashes)), 4)

    def test_compile_mixes_tracks_not_every_audio_clip(self):
        data = project()
        data["timeline"]["audioTracks"][0]["clips"].append({
            "source": "v.wav", "start": 5.5, "in": 1, "duration": 1,
        })
        data["timeline"]["audioTracks"].append({
            "id": "bed", "clips": [{"source": "bed.wav", "start": 0, "duration": 6.5}],
        })
        graph = AgentCutEngine().compile(data).filter_graph
        self.assertIn("[1:a]asplit=2", graph)
        self.assertIn("amix=inputs=2:duration=longest", graph)
        self.assertNotIn("amix=inputs=3", graph)

    def test_narrative_gate_rejects_duplicate_empty_irrelevant_budget_and_missing(self):
        data = project()
        data["narrativeGate"] = {
            "enabled": True, "maxSemanticRepeats": 1, "maxBackgroundBedRatio": .1,
            "maxBackgroundBedSeconds": .2, "requiredShotIds": ["must-have"],
        }
        data["timeline"]["videoTracks"][0]["clips"] = [
            {"id": "a", "source": "a.mp4", "start": 0, "duration": 1,
             "metadata": {"narrative_role": "action", "semantic_id": "same", "information_ids": ["fact-1"]}},
            {"id": "b", "source": "a.mp4", "start": 1, "duration": 1,
             "metadata": {"narrative_role": "action", "semantic_id": "same", "information_ids": ["fact-2"]}},
            {"id": "c", "source": "a.mp4", "start": 2, "duration": 1,
             "metadata": {"narrative_role": "reaction", "semantic_id": "reaction"}},
            {"id": "d", "source": "a.mp4", "start": 3, "duration": 1,
             "metadata": {"narrative_role": "cutaway", "semantic_id": "cut", "information_ids": ["fact-3"], "relevance_to": ["unknown"]}},
            {"id": "e", "source": "a.mp4", "start": 4, "duration": 1,
             "metadata": {"narrative_role": "background", "semantic_id": "bed"}},
        ]
        report = AgentCutEngine().validate(data)
        codes = {issue.code for issue in report.issues}
        self.assertFalse(report.valid)
        self.assertTrue({"NARRATIVE_SEMANTIC_DUPLICATE", "NARRATIVE_NO_NEW_INFORMATION",
                         "CUTAWAY_CONTEXT_MISMATCH", "BACKGROUND_BED_BUDGET_EXCEEDED",
                         "BACKGROUND_BED_CLIP_BUDGET_EXCEEDED", "REQUIRED_SHOTS_MISSING"}.issubset(codes))

    def test_narrative_gate_valid_project_and_render_preflight(self):
        data = project()
        data["narrativeGate"] = {"enabled": True, "requiredShotIds": ["hero-arrives"]}
        data["timeline"]["videoTracks"][0]["clips"][0].update({
            "id": "hero-arrives", "metadata": {"narrative_role": "action", "semantic_id": "arrival",
                                                   "information_ids": ["beat-arrival"], "shot_id": "hero-arrives",
                                                   "fallback_only": False},
        })
        data["timeline"]["audioTracks"][0]["clips"][0]["duration"] = 30
        report = AgentCutEngine().validate(data)
        self.assertTrue(report.valid, [x.to_dict() for x in report.issues])
        self.assertEqual(report.coverage["narrative"]["missingShotIds"], [])
        data["timeline"]["videoTracks"][0]["clips"][0]["metadata"] = {}
        with self.assertRaisesRegex(ValidationError, "NARRATIVE_METADATA_REQUIRED"):
            AgentCutEngine().render(data, overwrite=True)

    def test_short_narrative_segment_allows_three_distinct_semantics(self):
        def metadata(group, information):
            return {
                "narrative_function": "advance the E20 B03 power-recognition beat",
                "new_information": information,
                "semantic_group": group,
                "fallback_only": False,
            }

        data = {
            "version": "1.0",
            "output": {"path": "e20-b03-short-segment.mp4", "width": 720, "height": 1280},
            "timeline": {"videoTracks": [{"id": "Video.Main", "clips": [
                {"id": "commander-bow", "source": "commander.mp4", "start": 0, "duration": 3.0,
                 "metadata": metadata("COMMANDER_RECOGNIZES_RANK", "The bow establishes Bai Li's authority.")},
                {"id": "baili-signal", "source": "baili.mp4", "start": 3.0, "duration": 2.5,
                 "metadata": metadata("BAILI_RETURNS_SIGNAL", "Bai Li confirms the command without exposing herself.")},
                {"id": "chenji-eyes", "source": "chenji.mp4", "start": 5.5, "duration": 2.2,
                 "metadata": metadata("CHENJI_RECOGNIZES_DANGER", "Chenji understands her hidden rank and the danger.")},
            ]}]},
        }
        report = AgentCutEngine().validate(data)
        self.assertTrue(report.valid, [issue.to_dict() for issue in report.issues])
        self.assertAlmostEqual(report.duration, 7.7)
        budget = report.coverage["narrative"]["semanticBudget"]
        self.assertEqual(budget["mode"], "repeated-groups-only")
        self.assertEqual(budget["maxGroupRatio"], 0.15)
        self.assertEqual(budget["evaluatedGroups"], [])
        self.assertEqual(len(budget["singleUseGroups"]), 3)

        # A real repetition remains governed by both the ratio and cooldown
        # contracts; the short-segment exemption is not a duplicate bypass.
        data["timeline"]["videoTracks"][0]["clips"][1]["metadata"]["semantic_group"] = "COMMANDER_RECOGNIZES_RANK"
        report = AgentCutEngine().validate(data)
        codes = {issue.code for issue in report.issues}
        self.assertIn("SEMANTIC_GLOBAL_BUDGET_EXCEEDED", codes)
        self.assertIn("SEMANTIC_COOLDOWN_CONSECUTIVE", codes)

        # Raising only the global budget cannot disable duplicate/cooldown
        # checks when the project explicitly requires them.
        data["narrativeGate"] = {
            "enabled": True,
            "maxSemanticGroupRatio": 1.0,
            "rejectDuplicateSemantics": True,
            "maxSemanticRepeats": 1,
        }
        report = AgentCutEngine().validate(data)
        codes = {issue.code for issue in report.issues}
        self.assertNotIn("SEMANTIC_GLOBAL_BUDGET_EXCEEDED", codes)
        self.assertIn("NARRATIVE_SEMANTIC_DUPLICATE", codes)
        self.assertIn("SEMANTIC_COOLDOWN_CONSECUTIVE", codes)

    def test_semantic_group_ratio_configuration_is_bounded(self):
        data = project()
        data["narrativeGate"] = {"enabled": True, "maxSemanticGroupRatio": 0}
        with self.assertRaisesRegex(ValidationError, "maxSemanticGroupRatio"):
            AgentCutEngine().load(data)
        data["narrativeGate"]["maxSemanticGroupRatio"] = 1.01
        with self.assertRaisesRegex(ValidationError, "maxSemanticGroupRatio"):
            AgentCutEngine().load(data)

    def test_track_limits_are_enforced(self):
        data = project()
        data["timeline"]["videoTracks"] *= 3
        with self.assertRaisesRegex(ValidationError, "at most 2"):
            AgentCutEngine().load(data)

    def test_empty_timeline_is_rejected(self):
        data = project()
        data["timeline"] = {}
        with self.assertRaisesRegex(ValidationError, "at least one"):
            AgentCutEngine().load(data)

    def test_per_job_thread_limit(self):
        data = project()
        data["output"]["threads"] = 2
        argv = AgentCutEngine().compile(data).argv
        self.assertEqual(argv[argv.index("-threads") + 1], "2")

    def test_agent_health_protocol(self):
        output = io.StringIO()
        AgentServer(AgentCutEngine(), workers=2).serve(
            io.StringIO('{"id":"task2","method":"health","params":{}}\n'), output
        )
        response = json.loads(output.getvalue())
        self.assertTrue(response["ok"])
        self.assertEqual(response["id"], "task2")
        self.assertEqual(response["result"]["status"], "ready")
        self.assertTrue(response["result"]["capabilities"]["requireCutReason"])
        self.assertEqual(response["result"]["capabilities"]["continuityGate"]["mode"], "strict")
        self.assertEqual(response["result"]["capabilities"]["audioMastering"]["mode"], "measured-two-pass")
        self.assertTrue(response["result"]["capabilities"]["audioMastering"]["atomicOutput"])
        self.assertEqual(
            response["result"]["capabilities"]["continuityGate"]["requiredMetadata"],
            ["cut_reason", "scene_id", "light_key", "axis_line", "eyeline"],
        )

    def test_require_cut_reason_is_a_strict_preflight_gate(self):
        data = project()
        data["requireCutReason"] = True
        report = AgentCutEngine().validate(data)
        self.assertFalse(report.valid)
        self.assertEqual(report.issues[0].code, "CUT_REASON_REQUIRED")
        self.assertEqual(report.coverage["cutReason"]["missing"][0]["missingFields"], [
            "cut_reason", "scene_id", "light_key", "axis_line", "eyeline",
        ])
        with self.assertRaisesRegex(ValidationError, "CUT_REASON_REQUIRED"):
            AgentCutEngine().compile(data)

        data["timeline"]["videoTracks"][0]["clips"][0]["metadata"] = {
            "cut_reason": "切至角色反应以确认信息落点",
            "scene_id": "scene-01",
            "light_key": "window-left-soft",
            "axis_line": "hero-villain-180",
            "eyeline": "hero-right-villain-left",
        }
        report = AgentCutEngine().validate(data)
        self.assertTrue(report.valid, [issue.to_dict() for issue in report.issues])
        self.assertEqual(report.coverage["cutReason"]["missing"], [])

    def test_clip_identity_is_preserved_in_compile_summary(self):
        data = project()
        data["timeline"]["videoTracks"][0]["clips"][0].update({
            "id": "clip-dialogue-42", "metadata": {"dialogue_id": "d42", "beat_id": "b7"}
        })
        summary = AgentCutEngine().compile(data).summary
        clip = summary["clips"][0]
        self.assertEqual(clip["clipId"], "clip-dialogue-42")
        self.assertEqual(clip["metadata"]["dialogue_id"], "d42")
        self.assertEqual(clip["trackId"], "A")
        self.assertEqual(clip["clipIndex"], 0)

    def test_strict_media_detects_production_black_gap_with_clip_context(self):
        data = {
            "version": "1.0", "output": {"path": "out.mp4"},
            "timeline": {
                "videoTracks": [{"id": "base", "clips": [{
                    "id": "last-shot", "metadata": {"dialogue_id": "d88"},
                    "source": "video.mp4", "start": 0, "duration": 105.542,
                }]}],
                "audioTracks": [{"id": "dialogue", "clips": [{
                    "id": "last-line", "metadata": {"beat_id": "b99"},
                    "source": "audio.wav", "start": 0, "duration": 109.583,
                }]}],
            },
        }
        probes = {
            "video.mp4": {"format": {"duration": "200"}, "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264"}]},
            "audio.wav": {"format": {"duration": "200"}, "streams": [{"index": 0, "codec_type": "audio", "codec_name": "aac"}]},
        }
        with patch.object(MediaValidator, "_probe", side_effect=lambda source: probes[source]):
            report = AgentCutEngine().validate(data, strict_media=True)
        self.assertFalse(report.valid)
        gap = next(x.to_dict() for x in report.issues if x.code == "VIDEO_GAP")
        self.assertAlmostEqual(gap["timeRange"]["start"], 105.542)
        self.assertAlmostEqual(gap["timeRange"]["end"], 109.583)
        self.assertEqual(gap["relatedClips"][0]["clipId"], "last-shot")
        self.assertEqual(gap["relatedClips"][0]["metadata"]["dialogue_id"], "d88")

    def test_strict_media_rejects_source_bounds_and_missing_stream(self):
        data = project()
        data["timeline"]["videoTracks"][0]["clips"][0].update({"id": "bad-source", "metadata": {"beat_id": "b2"}})
        probes = {
            "a.mp4": {"format": {"duration": "3"}, "streams": [{"index": 0, "codec_type": "audio", "codec_name": "aac"}]},
            "v.wav": {"format": {"duration": "10"}, "streams": [{"index": 0, "codec_type": "audio", "codec_name": "aac"}]},
        }
        with patch.object(MediaValidator, "_probe", side_effect=lambda source: probes[source]):
            report = AgentCutEngine().validate(data, strict_media=True)
        issues = {x.code: x.to_dict() for x in report.issues}
        self.assertIn("MISSING_STREAM", issues)
        self.assertIn("CLIP_SOURCE_OUT_OF_BOUNDS", issues)
        self.assertEqual(issues["CLIP_SOURCE_OUT_OF_BOUNDS"]["clipId"], "bad-source")
        self.assertEqual(issues["CLIP_SOURCE_OUT_OF_BOUNDS"]["metadata"]["beat_id"], "b2")

    def test_bounds_use_matching_stream_duration_not_longer_container(self):
        data = project()
        probes = {
            "a.mp4": {"format": {"duration": "10"}, "streams": [{"index": 0, "codec_type": "video", "duration": "4", "codec_name": "h264"}]},
            "v.wav": {"format": {"duration": "10"}, "streams": [{"index": 0, "codec_type": "audio", "duration": "10", "codec_name": "aac"}]},
        }
        with patch.object(MediaValidator, "_probe", side_effect=lambda source: probes[source]):
            report = AgentCutEngine().validate(data, strict_media=True)
        self.assertTrue(any(x.code == "CLIP_SOURCE_OUT_OF_BOUNDS" and x.track_kind == "video" for x in report.issues))

    def test_agent_render_is_compact_unless_command_requested(self):
        engine = Mock()
        engine.render.return_value = RenderResult("/tmp/out.mp4", 12.5, ("ffmpeg", "-i", "many-inputs"))
        server = AgentServer(engine, workers=1)
        compact = server.handle({"id": "r1", "method": "render", "params": {"project": {}}})
        verbose = server.handle({"id": "r2", "method": "render", "params": {"project": {}, "includeCommand": True}})
        self.assertEqual(compact["result"], {"output": "/tmp/out.mp4", "duration": 12.5})
        self.assertNotIn("command", compact["result"])
        self.assertEqual(verbose["result"]["command"][0], "ffmpeg")

    def test_agent_can_emit_opt_in_progress_events(self):
        engine = Mock()
        def render(_project, *, overwrite, on_progress):
            on_progress(RenderProgress(5, 10, .5))
            return RenderResult("/tmp/out.mp4", 10, ("ffmpeg",))
        engine.render.side_effect = render
        events = []
        response = AgentServer(engine, workers=1).handle(
            {"id": "r1", "method": "render", "params": {"project": {}, "progress": True}}, events.append
        )
        self.assertTrue(response["ok"])
        self.assertEqual(events[0]["progress"], 0.0)
        self.assertEqual(events[1]["progress"], 0.5)

    def test_timeline_transform_trims_av_once_and_ripples_all_tracks(self):
        result = AgentCutEngine().transform(trim_project(), trim_plan(), dry_run=True)
        self.assertTrue(result.valid)
        self.assertEqual(result.transformed.total_trim, 0.4)
        transformed = result.transformed.project["timeline"]
        video, audio = transformed["videoTracks"][0]["clips"], transformed["audioTracks"][0]["clips"]
        for clips in (video, audio):
            self.assertAlmostEqual(clips[0]["in"], 0.2)
            self.assertAlmostEqual(clips[0]["duration"], 0.8)
            self.assertAlmostEqual(clips[1]["start"], 0.8)
            self.assertAlmostEqual(clips[1]["in"], 0.2)
            self.assertAlmostEqual(clips[1]["duration"], 0.8)
            self.assertAlmostEqual(clips[2]["start"], 1.6)
            self.assertEqual(clips[2]["duration"], 1)
        self.assertFalse(result.transformed.audit["invariants"]["speedChanged"])

    def test_transform_audit_is_deterministic_and_rolls_back_exactly(self):
        engine = AgentCutEngine()
        first = engine.transform(trim_project(), trim_plan(), dry_run=True).transformed
        second = engine.transform(trim_project(), trim_plan(), dry_run=True).transformed
        self.assertEqual(first.audit, second.audit)
        rolled_back = engine.rollback(first.audit, dry_run=True)["project"]
        self.assertEqual(content_hash(rolled_back), first.audit["beforeHash"])
        self.assertEqual(rolled_back, trim_project())

    def test_protected_beat_cannot_be_head_trimmed(self):
        plan = trim_plan()
        plan["expectedOperationCount"] = 1
        plan["expectedTotalTrim"] = 0.2
        plan["operations"] = [{"id": "bad-b05", "match": {"dialogueId": "D3"}, "headTrim": 0.2,
                               "contentGuard": "silence-head", "requiredTrackKinds": ["video", "audio"]}]
        with self.assertRaisesRegex(ValidationError, "protected clip"):
            AgentCutEngine().transform(trim_project(), plan, dry_run=True)

    def test_frozen_beat_blocks_prior_ripple(self):
        plan = trim_plan()
        plan["protections"] = {"frozenBeatIds": ["B05"]}
        with self.assertRaisesRegex(ValidationError, "ripple frozen clip"):
            AgentCutEngine().transform(trim_project(), plan, dry_run=True)

    def test_transform_writes_project_and_audit_then_cli_style_rollback(self):
        engine = AgentCutEngine()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "transformed.json"
            audit = Path(directory) / "audit.json"
            restored = Path(directory) / "restored.json"
            result = engine.transform(trim_project(), trim_plan(), dry_run=False, output=output, audit_path=audit)
            self.assertTrue(output.exists() and audit.exists())
            rolled_back = engine.rollback(audit, output=restored)
            self.assertEqual(rolled_back["projectHash"], content_hash(trim_project()))
            self.assertEqual(json.loads(restored.read_text()), trim_project())

    def test_ndjson_transform_defaults_to_safe_dry_run(self):
        response = AgentServer(AgentCutEngine(), workers=1).handle({
            "id": "t1", "method": "transformProject",
            "params": {"project": trim_project(), "plan": trim_plan()},
        })
        self.assertTrue(response["ok"])
        self.assertTrue(response["result"]["dryRun"])
        self.assertEqual(response["result"]["totalTrim"], 0.4)
        self.assertNotIn("project", response["result"])

    def test_e18r_scale_33_operations_total_is_exactly_6_6(self):
        def make_clip(kind, index):
            dialogue = f"E18R-{index:03d}"
            return {"id": f"{kind}-{dialogue}", "metadata": {"dialogue_id": dialogue, "beat_id": "E18R"},
                    "source": f"{kind}.media", "start": float(index), "in": 0, "duration": 1}
        frozen_video = {"id": "v-b05", "metadata": {"dialogue_id": "B05-001", "beat_id": "B05"},
                        "source": "v.media", "start": 0, "in": 0, "duration": 1}
        frozen_audio = {**frozen_video, "id": "a-b05", "source": "a.media"}
        data = {
            "version": "1.0", "output": {"path": "out.mp4"},
            "timeline": {
                "videoTracks": [{"id": "A", "clips": [frozen_video] + [make_clip("v", i) for i in range(1, 34)]}],
                "audioTracks": [{"id": "dialogue", "clips": [frozen_audio] + [make_clip("a", i) for i in range(1, 34)]}],
            },
        }
        plan = {
            "version": "1.0", "expectedOperationCount": 33, "expectedTotalTrim": 6.6,
            "operations": [{"id": f"trim-{i:03d}", "match": {"dialogueId": f"E18R-{i:03d}"},
                            "headTrim": 0.2, "contentGuard": "silence-head",
                            "requiredTrackKinds": ["video", "audio"]} for i in range(1, 34)],
            "protections": {"frozenBeatIds": ["B05"]},
            "options": {"ripple": True, "maxHeadTrim": 0.2, "preserveTrackOrder": True},
        }
        result = AgentCutEngine().transform(data, plan, dry_run=True).transformed
        self.assertEqual(result.total_trim, 6.6)
        self.assertEqual(result.audit["operationCount"], 33)
        self.assertEqual(result.project["timeline"]["videoTracks"][0]["clips"][0]["start"], 0)
        self.assertAlmostEqual(result.project["timeline"]["videoTracks"][0]["clips"][-1]["start"], 26.6)

    def test_strict_transform_failure_does_not_write_project_or_audit(self):
        probes = {
            "v.mp4": {"format": {"duration": "0.5"}, "streams": [{"codec_type": "video", "duration": "0.5"}]},
            "a.wav": {"format": {"duration": "10"}, "streams": [{"codec_type": "audio", "duration": "10"}]},
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(
            MediaValidator, "_probe", side_effect=lambda source: probes[source]
        ):
            output = Path(directory) / "must-not-exist.json"
            audit = Path(directory) / "must-not-exist.audit.json"
            result = AgentCutEngine().transform(
                trim_project(), trim_plan(), dry_run=False, output=output,
                audit_path=audit, strict_media=True,
            )
            self.assertFalse(result.valid)
            self.assertFalse(output.exists())
            self.assertFalse(audit.exists())
            self.assertTrue(any(x.code == "CLIP_SOURCE_OUT_OF_BOUNDS" for x in result.validation.issues))

    def test_final_visual_gate_rejects_unmotivated_near_freeze_with_evidence(self):
        engine = AgentCutEngine()
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "static.mp4"
            report_path = Path(directory) / "static-report.json"
            made = subprocess.run([
                engine.ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                "color=c=0x203060:s=160x284:r=24:d=5.5,drawbox=x=20:y=30:w=60:h=80:c=white:t=fill",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(video),
            ], capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            result = engine.validate_final_visual(video, report=report_path)
            self.assertFalse(result["hardGatePassed"])
            freeze = next(item for item in result["violations"] if item["code"] == "FINAL_NEAR_FREEZE_EXCEEDED")
            self.assertGreater(freeze["timeCluster"]["duration"], 4)
            self.assertLessEqual(freeze["evidence"]["motionMean"]["max"], 0.018)
            self.assertEqual(freeze["threshold"]["maxNearFreezeSeconds"], 4)
            self.assertTrue(report_path.is_file())
            self.assertFalse(result["platformMutationAuthorized"])

    def test_final_visual_gate_rejects_third_repeated_composition_cluster(self):
        engine = AgentCutEngine()
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "repeat.mp4"
            inputs = []
            for index in range(6):
                x = 12 if index % 2 == 0 else 95
                inputs.extend(["-f", "lavfi", "-i",
                               f"color=c=black:s=160x284:r=24:d=1,drawbox=x={x}:y=40:w=40:h=90:c=white:t=fill"])
            made = subprocess.run([
                engine.ffmpeg, "-v", "error", *inputs, "-filter_complex",
                "[0:v][1:v][2:v][3:v][4:v][5:v]concat=n=6:v=1:a=0[v]",
                "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(video),
            ], capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            result = engine.validate_final_visual(video, policy={
                "enabled": True, "required": True, "sampleFps": 2,
                "maxNearFreezeSeconds": 20, "minCompositionOccurrenceSeconds": 0.5,
                "compositionGapSeconds": 0.25,
                "maxCompositionOccurrences": 2, "maxCompositionRatio": 1,
            })
            duplicate = next(item for item in result["violations"]
                             if item["code"] == "FINAL_NEAR_DUPLICATE_COMPOSITION_EXCEEDED")
            self.assertGreater(duplicate["occurrenceCount"], 2)
            self.assertIn("occurrence_count_exceeded", duplicate["reasons"])
            self.assertGreaterEqual(len(duplicate["timeClusters"]), 3)

    def test_final_visual_policy_is_backward_compatible_and_bounded(self):
        parsed = AgentCutEngine().load(project())
        self.assertFalse(parsed.final_visual_policy.enabled)
        self.assertFalse(parsed.final_visual_policy.required)
        data = project()
        data["finalVisualPolicy"] = {"enabled": True, "sampleFps": 0}
        with self.assertRaisesRegex(ValidationError, "sampleFps"):
            AgentCutEngine().load(data)
        data["finalVisualPolicy"] = {"enabled": True, "allowedIntervals": [{"start": 1, "end": 2}]}
        with self.assertRaisesRegex(ValidationError, "reason"):
            AgentCutEngine().load(data)

    def test_ndjson_final_visual_gate_parity(self):
        engine = AgentCutEngine()
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "static.mp4"
            report = Path(directory) / "ndjson-report.json"
            made = subprocess.run([
                engine.ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                "color=c=navy:s=160x284:r=24:d=5", "-an", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-y", str(video),
            ], capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            response = AgentServer(engine, workers=1).handle({
                "id": "visual", "method": "validateFinalVisual",
                "params": {"final": str(video), "report": str(report)},
            })
            self.assertTrue(response["ok"])
            self.assertFalse(response["result"]["hardGatePassed"])
            self.assertTrue(report.is_file())

    def test_render_final_visual_failure_is_atomic(self):
        engine = AgentCutEngine()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "static-source.mp4"
            output = Path(directory) / "must-not-output.mp4"
            made = subprocess.run([
                engine.ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                "color=c=green:s=160x284:r=24:d=5.5", "-an", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-y", str(source),
            ], capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            data = {
                "version": "1.0", "output": {"path": str(output), "width": 160, "height": 284, "fps": 24},
                "finalVisualPolicy": {"enabled": True, "required": True},
                "timeline": {"videoTracks": [{"id": "Video.Main", "clips": [
                    {"id": "STATIC", "source": str(source), "duration": 5.5},
                ]}]},
            }
            with self.assertRaisesRegex(AgentCutError, "final visual hard gate failed"):
                engine.render(data)
            self.assertFalse(output.exists())
            failed_report = Path(str(output) + ".failed-visual-qa.json")
            self.assertTrue(failed_report.is_file())
            self.assertFalse(json.loads(failed_report.read_text())["hardGatePassed"])

    @unittest.skipUnless(E28_V3_FINAL.is_file() and E28_V3_PROJECT.is_file(), "E28 V3 production evidence unavailable")
    def test_e28_v3_real_fullcut_blind_spot_is_blocked(self):
        result = AgentCutEngine().validate_final_visual(self.E28_V3_FINAL, project=self.E28_V3_PROJECT)
        self.assertFalse(result["hardGatePassed"])
        freeze_ranges = [(item["timeCluster"]["start"], item["timeCluster"]["end"])
                         for item in result["violations"] if item["code"] == "FINAL_NEAR_FREEZE_EXCEEDED"]
        self.assertTrue(any(start <= 91 and end >= 95 for start, end in freeze_ranges))
        self.assertTrue(any(start <= 101.5 and end >= 106 for start, end in freeze_ranges))
        duplicate = next(item for item in result["violations"]
                         if item["code"] == "FINAL_NEAR_DUPLICATE_COMPOSITION_EXCEEDED")
        self.assertGreater(duplicate["nearDuplicateRatio"], 0.06)
        self.assertTrue(any(cluster["start"] <= 91 and cluster["end"] >= 95 for cluster in duplicate["timeClusters"]))

    @unittest.skipUnless(E28_V4_FINAL.is_file() and E28_V4_PROJECT.is_file(), "E28 V4 production evidence unavailable")
    def test_e28_v4_real_recut_clears_midsection_but_remaining_freezes_stay_blocked(self):
        result = AgentCutEngine().validate_final_visual(self.E28_V4_FINAL, project=self.E28_V4_PROJECT)
        self.assertFalse(result["hardGatePassed"])
        freezes = [item["timeCluster"] for item in result["violations"]
                   if item["code"] == "FINAL_NEAR_FREEZE_EXCEEDED"]
        self.assertFalse(any(item["start"] < 107 and item["end"] > 85 for item in freezes))
        self.assertTrue(any(item["start"] <= 64 and item["end"] >= 69 for item in freezes))
        self.assertFalse(any(item["code"] == "FINAL_NEAR_DUPLICATE_COMPOSITION_EXCEEDED"
                             for item in result["violations"]))


if __name__ == "__main__":
    unittest.main()
