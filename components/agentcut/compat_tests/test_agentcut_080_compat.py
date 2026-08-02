import unittest
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from agentcut import AgentCutEngine, RenderProgress, RenderResult, ValidationError
from agentcut.agent import AgentServer
from agentcut.validation import MediaValidator
from agentcut.transform import content_hash
from agentcut.isolation import isolation_confidence
from agentcut.audio_backend import audio_save_health, require_audio_save_backend
from agentcut.giggle import finalize_first_last_submission, prepare_first_last_submission
from agentcut.longtake import LongTakeValidator, longtake_preflight


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

    def test_compile_burns_chinese_captions_in_9x16_safe_area(self):
        data = subtitled_project()
        data["output"].update({"width": 720, "height": 1280})
        compiled = AgentCutEngine().compile(data)
        self.assertIn("drawtext=text='半夜送礼'", compiled.filter_graph)
        self.assertIn(f"fontfile='{CHINESE_FONT}'", compiled.filter_graph)
        self.assertIn("y=h-text_h-160", compiled.filter_graph)
        self.assertEqual(compiled.summary["subtitleTracks"], 1)
        self.assertEqual(len(compiled.summary["captions"]), 2)

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
        self.assertEqual(response["result"]["version"], "0.9.17")
        self.assertEqual(len(response["result"]["runtimeHash"]), 64)
        self.assertTrue(response["result"]["ffmpegInfo"]["available"])
        self.assertEqual(len(response["result"]["ffmpegInfo"]["sha256"]), 64)

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

    def test_cl2x_298_require_cut_reason_rejects_missing_reason_before_transform(self):
        plan = trim_plan()
        plan["requireCutReason"] = True
        with self.assertRaisesRegex(ValidationError, r"operations\[0\]\.cutReason is required by requireCutReason"):
            AgentCutEngine().transform(trim_project(), plan, dry_run=True)

    def test_cl2x_298_cut_reason_is_preserved_in_deterministic_audit(self):
        plan = trim_plan()
        plan["requireCutReason"] = True
        for operation in plan["operations"]:
            operation["cutReason"] = "remove verified silence head"
        result = AgentCutEngine().transform(trim_project(), plan, dry_run=True).transformed
        self.assertTrue(result.audit["contract"]["requireCutReason"])
        self.assertEqual(result.audit["operations"][0]["cutReason"], "remove verified silence head")
        self.assertTrue(result.summary()["requireCutReason"])

    def test_ndjson_can_force_cut_reason_contract_even_when_plan_omits_flag(self):
        with self.assertRaisesRegex(ValidationError, "cutReason is required"):
            AgentServer(AgentCutEngine(), workers=1).handle({
                "id": "cl2x-298", "method": "transformProject",
                "params": {"project": trim_project(), "plan": trim_plan(), "requireCutReason": True},
            })

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

    def test_cl2x352_multi_image_without_guarantee_fails_before_payment(self):
        result = longtake_preflight({
            "version": "1.0", "paidSubmission": True, "continuousCameraRequired": True,
            "input": {"mode": "multi-image", "anchors": [
                {"id": "B01", "time": 0}, {"id": "B02", "time": 5}, {"id": "B03", "time": 10},
            ], "cueBlocks": [{"start": 0, "end": 5}, {"start": 5, "end": 10}]},
            "provider": {"name": "Seedance", "guaranteesInterAnchorInterpolation": False},
        })
        self.assertFalse(result["allowed"])
        self.assertEqual(result["decision"], "FAIL_BEFORE_PAID_SUBMISSION")
        self.assertIn("LONG_TAKE_INTERPOLATION_GUARANTEE_REQUIRED", {x["code"] for x in result["issues"]})

    def test_cl2x352_single_anchor_is_not_blocked_by_multi_image_gate(self):
        result = longtake_preflight({
            "version": "1.0", "input": {"mode": "single-anchor", "anchors": [{"id": "B01", "time": 0}]},
            "provider": {"name": "Seedance", "guaranteesInterAnchorInterpolation": False},
        })
        self.assertTrue(result["allowed"])

    def test_cl2x352_hard_cut_detector_preserves_exact_e23_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "candidate.mp4"
            video.write_bytes(b"candidate")
            probe = Mock(returncode=0, stdout='{"format":{"duration":"15.069"}}', stderr="")
            detect = Mock(
                returncode=0, stdout="",
                stderr="[Parsed_showinfo] pts_time:4.666667\n[Parsed_showinfo] pts_time:9.541667\n",
            )
            with patch("agentcut.longtake.shutil.which", return_value="/usr/bin/tool"), \
                 patch("agentcut.longtake.subprocess.run", side_effect=[probe, detect]):
                result = LongTakeValidator("ffmpeg", "ffprobe").validate(video, anchor_times=[5, 10])
        self.assertFalse(result["valid"])
        self.assertEqual([x["time"] for x in result["hardCuts"]], [4.666667, 9.541667])
        self.assertTrue(all(x["interAnchorHardCut"] for x in result["hardCuts"]))

    def test_cl2x353_first_last_contract_routes_exact_roles_without_omni_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            start, end = base / "B01.png", base / "B03.png"
            start.write_bytes(b"start")
            end.write_bytes(b"end")
            task = {
                "version": "1.0", "task_key": "E23-B01-to-B03",
                "generation_mode": "image_to_video_first_last", "prompt": "continuous take",
                "inputs": [{"role": "start_frame", "source": str(start)}, {"role": "end_frame", "source": str(end)}],
                "model": "seedance-2.0-pro", "duration": 15, "aspect_ratio": "9:16", "resolution": "720p",
            }
            result = prepare_first_last_submission(task, include_command=True)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["request"]["endpoint"], "/api/v1/generation/image-to-video")
        self.assertEqual(set(result["inputRoles"]), {"start_frame", "end_frame"})
        self.assertIn("image-to-video", result["argv"])
        self.assertNotIn("omni-video", result["argv"])
        self.assertNotIn("--reference-image", result["argv"])

    def test_cl2x353_rejects_duplicate_role_and_generic_images_before_payment(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = Path(directory) / "frame.png"
            frame.write_bytes(b"frame")
            base = {
                "version": "1.0", "taskKey": "E23", "generationMode": "image_to_video_first_last",
                "prompt": "continuous", "inputs": [
                    {"role": "start_frame", "source": str(frame)},
                    {"role": "start_frame", "source": str(frame)},
                ],
                "model": "seedance-2.0-pro", "duration": 15, "aspectRatio": "9:16", "resolution": "720p",
            }
            with self.assertRaisesRegex(ValidationError, "duplicate role"):
                prepare_first_last_submission(base)
            base["referenceImages"] = [str(frame)]
            with self.assertRaisesRegex(ValidationError, "do not fall back to images"):
                prepare_first_last_submission(base)

    def test_cl2x353_ndjson_prepare_is_compact_unless_command_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = Path(directory) / "frame.png"
            frame.write_bytes(b"frame")
            task = {
                "version": "1.0", "taskKey": "E23", "generationMode": "image_to_video_first_last",
                "prompt": "continuous", "inputs": [
                    {"role": "start_frame", "source": str(frame)},
                    {"role": "end_frame", "source": str(frame)},
                ],
                "model": "seedance-2.0-pro", "duration": 15, "aspectRatio": "9:16", "resolution": "720p",
            }
            server = AgentServer(AgentCutEngine(), workers=1)
            compact = server.handle({"id": "p1", "method": "prepareFirstLastGeneration", "params": {"task": task}})
            verbose = server.handle({"id": "p2", "method": "prepareFirstLastGeneration", "params": {"task": task, "includeCommand": True}})
        self.assertNotIn("argv", compact["result"])
        self.assertIn("argv", verbose["result"])

    def test_cl2x353_finalize_receipt_rejects_hard_cut_and_keeps_task_sha_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            frame, video = base / "frame.png", base / "candidate.mp4"
            frame.write_bytes(b"frame")
            video.write_bytes(b"candidate")
            task = {
                "version": "1.0", "taskKey": "E23-B04-to-B06", "generationMode": "image_to_video_first_last",
                "prompt": "continuous", "inputs": [
                    {"role": "start_frame", "source": str(frame)}, {"role": "end_frame", "source": str(frame)},
                ],
                "model": "seedance-2.0-pro", "duration": 15, "aspectRatio": "9:16", "resolution": "720p",
            }
            probe = Mock(returncode=0, stdout='{"format":{"duration":"15.069"}}', stderr="")
            detect = Mock(returncode=0, stdout="", stderr="[showinfo] pts_time:9.375\n")
            with patch("agentcut.longtake.shutil.which", return_value="/usr/bin/tool"), \
                 patch("agentcut.longtake.subprocess.run", side_effect=[probe, detect]):
                receipt = finalize_first_last_submission(
                    task, video, "remote-task-123", ffmpeg="ffmpeg", ffprobe="ffprobe",
                )
        self.assertFalse(receipt["accepted"])
        self.assertEqual(receipt["decision"], "REJECT_HARD_CUT")
        self.assertEqual(receipt["taskId"], "remote-task-123")
        self.assertEqual(receipt["endpoint"], "/api/v1/generation/image-to-video")
        self.assertEqual(receipt["continuityAudit"]["hardCuts"][0]["time"], 9.375)
        self.assertEqual(len(receipt["video"]["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
