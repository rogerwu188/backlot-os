import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from agentcut import AgentCutEngine, ValidationError
from agentcut.agent import AgentServer
from agentcut.shot_recipes import list_short_drama_recipes


def recipe_project(source="fixture.mp4", output="recipe_acceptance.mp4", *, fps=24, duration=4.0,
                   recipe_id="camera.slow_push_in", version="1.0.0"):
    return {
        "version": "1.0",
        "output": {"path": output, "width": 720, "height": 1280, "fps": fps, "threads": 1},
        "shotRecipePolicy": {
            "enabled": True,
            "registryId": "agentcut.short_drama.director_recipes",
            "registryVersion": "1.0.0",
            "projectOverrides": {recipe_id: {"subject_anchor": {"x_ratio": 0.48}}},
        },
        "timeline": {"videoTracks": [{"id": "Video.Main", "clips": [{
            "id": "SHOT-001", "source": source, "start": 0.25, "duration": duration,
            "metadata": {"shot_recipe": {
                "recipe_id": recipe_id, "version": version,
                "override": {"camera_motion": {"intensity": 0.7}},
            }},
        }]}]},
    }


class ShotRecipeTests(unittest.TestCase):
    def test_registry_is_curated_licensed_and_excludes_ui_only_cards(self):
        registry = list_short_drama_recipes()
        self.assertEqual(registry["registryVersion"], "1.0.0")
        self.assertEqual(registry["recipeCount"], 27)
        self.assertFalse(registry["remotionRequired"])
        self.assertFalse(registry["audioAssetsImported"])
        self.assertEqual(registry["layer"], "per_shot_director_execution")
        self.assertEqual(registry["styleTemplateBehavior"], "preserve_project_style")
        self.assertFalse(registry["styleOverrideAllowed"])
        for item in registry["recipes"]:
            self.assertFalse(item["applicability"]["ui_only"])
            self.assertEqual(item["license"]["spdx"], "Apache-2.0")
            self.assertNotIn("ui-entrance", item["source"]["path"])

    def test_valid_recipe_materializes_seconds_to_24fps_and_preserves_overrides(self):
        engine = AgentCutEngine()
        data = recipe_project()
        report = engine.validate(data)
        self.assertTrue(report.valid, [item.to_dict() for item in report.issues])
        coverage = report.coverage["shotRecipes"]
        self.assertEqual(coverage["status"], "PASS")
        item = coverage["materializedTimeline"][0]
        self.assertEqual(item["frameRange"], {"startFrame": 6, "endFrameExclusive": 102, "frameCount": 96})
        phases = {phase["phaseId"]: phase for phase in item["motionArc"]["phases"]}
        self.assertEqual(phases["setup"]["frameRange"]["startFrame"], 6)
        self.assertEqual(phases["setup"]["frameRange"]["endFrameExclusive"], 27)
        self.assertEqual(phases["contact"]["frameRange"]["endFrameExclusive"], 75)
        self.assertEqual(item["resolvedRecipe"]["subject_anchor"]["x_ratio"], 0.48)
        self.assertEqual(item["resolvedRecipe"]["camera_motion"]["intensity"], 0.7)
        self.assertEqual(item["provenance"]["projectOverridePaths"], ["subject_anchor.x_ratio"])
        self.assertEqual(item["provenance"]["clipOverridePaths"], ["camera_motion.intensity"])

        compiled = engine.compile(data)
        self.assertEqual(compiled.summary["clips"][0]["metadata"], data["timeline"]["videoTracks"][0]["clips"][0]["metadata"])
        self.assertEqual(compiled.summary["directorRenderPlan"]["clips"][0]["recipeId"], "camera.slow_push_in")
        self.assertEqual(compiled.summary["shotRecipes"]["materializedTimeline"][0]["resolvedRecipe"]["dramatic_intent"],
                         item["resolvedRecipe"]["dramatic_intent"])

    def test_unknown_recipe_and_missing_version_fail_validate_and_compile(self):
        engine = AgentCutEngine()
        unknown = recipe_project(recipe_id="camera.not_registered")
        report = engine.validate(unknown)
        self.assertFalse(report.valid)
        self.assertIn("SHOT_RECIPE_UNKNOWN", {item.code for item in report.issues})
        with self.assertRaisesRegex(ValidationError, "SHOT_RECIPE_UNKNOWN"):
            engine.compile(unknown)

        missing = recipe_project()
        del missing["timeline"]["videoTracks"][0]["clips"][0]["metadata"]["shot_recipe"]["version"]
        report = engine.validate(missing)
        self.assertFalse(report.valid)
        self.assertIn("SHOT_RECIPE_VERSION_MISSING", {item.code for item in report.issues})

    def test_motion_arc_and_sfx_cue_outside_clip_fail(self):
        engine = AgentCutEngine()
        motion = recipe_project()
        motion["timeline"]["videoTracks"][0]["clips"][0]["metadata"]["shot_recipe"]["override"] = {
            "motion_arc": {"phases": [{
                "phase_id": "contact", "start_seconds": 1.0, "end_seconds": 4.2,
                "description": "invalid overrun",
            }]}
        }
        report = engine.validate(motion)
        self.assertIn("SHOT_RECIPE_MOTION_ARC_OUT_OF_CLIP", {item.code for item in report.issues})

        sfx = recipe_project()
        sfx["timeline"]["videoTracks"][0]["clips"][0]["metadata"]["shot_recipe"]["override"] = {
            "sfx_cues": [{
                "cue_id": "late", "semantic": "late cue", "at_seconds": 4.5,
                "asset_path": None, "license": None, "license_status": "symbolic_only",
            }]
        }
        report = engine.validate(sfx)
        self.assertIn("SHOT_RECIPE_SFX_CUE_OUT_OF_CLIP", {item.code for item in report.issues})

    def test_intentional_black_requires_exact_frames_reason_and_policy(self):
        engine = AgentCutEngine()
        invalid = recipe_project(recipe_id="rhythm.blackout_slam")
        invalid["timeline"]["videoTracks"][0]["clips"][0]["metadata"]["intentional_black"] = True
        invalid["timeline"]["videoTracks"][0]["clips"][0]["metadata"]["shot_recipe"]["override"] = {
            "transition_intent": {"intentional_black": {
                "reference_fps": 30, "reference_start_frame": 48, "reference_duration_frames": 12,
                "reason": None, "approval_policy": None,
            }}
        }
        report = engine.validate(invalid)
        self.assertFalse(report.valid)
        self.assertIn("SHOT_RECIPE_INTENTIONAL_BLACK_EVIDENCE_REQUIRED", {item.code for item in report.issues})

        valid = recipe_project(recipe_id="rhythm.blackout_slam")
        valid["timeline"]["videoTracks"][0]["clips"][0]["metadata"]["intentional_black"] = True
        report = engine.validate(valid)
        self.assertTrue(report.valid, [item.to_dict() for item in report.issues])
        black = report.coverage["shotRecipes"]["materializedTimeline"][0]["intentionalBlack"]
        self.assertEqual(black["reference"], {"fps": 30, "startFrame": 48, "durationFrames": 12})
        self.assertEqual(black["frameRange"]["startFrame"], 44)
        self.assertEqual(black["frameRange"]["endFrameExclusive"], 54)
        self.assertEqual(black["frameRange"]["frameCount"], 10)

    def test_sfx_asset_without_per_file_license_is_rejected(self):
        data = recipe_project()
        data["timeline"]["videoTracks"][0]["clips"][0]["metadata"]["shot_recipe"]["override"] = {
            "sfx_cues": [{
                "cue_id": "unlicensed", "semantic": "impact", "phase_id": "contact",
                "asset_path": "/tmp/unverified.wav", "license": None,
            }]
        }
        report = AgentCutEngine().validate(data)
        self.assertIn("SHOT_RECIPE_SFX_LICENSE_UNVERIFIED", {item.code for item in report.issues})

    def test_repair_mapping_expands_aggregate_range_to_clip_phases(self):
        data = recipe_project(duration=4)
        second = copy.deepcopy(data["timeline"]["videoTracks"][0]["clips"][0])
        second["id"] = "SHOT-002"
        second["start"] = 4.25
        second["metadata"]["shot_recipe"]["recipe_id"] = "camera.pull_back_isolation"
        data["timeline"]["videoTracks"][0]["clips"].append(second)
        result = AgentCutEngine().map_shot_recipe_repairs(data, aggregate_problems=[{
            "code": "AGGREGATE_FREEZE", "message": "freeze cluster", "timeRange": {"start": 3.0, "end": 5.5},
        }])
        self.assertGreaterEqual(result["taskCount"], 2)
        self.assertEqual({task["clipId"] for task in result["tasks"]}, {"SHOT-001", "SHOT-002"})
        self.assertTrue(all(task["phaseId"] for task in result["tasks"]))
        self.assertTrue(all(task["platformMutationAuthorized"] is False for task in result["tasks"]))

    def test_ndjson_registry_and_repair_methods_match_sdk(self):
        server = AgentServer(AgentCutEngine(), workers=1)
        listed = server.handle({"id": "list", "method": "listShotRecipes", "params": {}})
        self.assertTrue(listed["ok"])
        self.assertEqual(listed["result"]["recipeCount"], 27)
        repaired = server.handle({
            "id": "repair", "method": "mapShotRecipeRepairs",
            "params": {"project": recipe_project(), "problems": [{"start": 1, "end": 2, "code": "CHECK"}]},
        })
        self.assertTrue(repaired["ok"])
        self.assertGreater(repaired["result"]["taskCount"], 0)

    def test_old_project_remains_not_requested(self):
        data = recipe_project()
        data.pop("shotRecipePolicy")
        data["timeline"]["videoTracks"][0]["clips"][0]["metadata"] = {}
        report = AgentCutEngine().validate(data)
        self.assertTrue(report.valid)
        self.assertEqual(report.coverage["shotRecipes"]["status"], "NOT_REQUESTED")

    def test_not_for_release_fixture_validate_compile_render_preserves_sidecar(self):
        engine = AgentCutEngine()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "synthetic_source.mp4"
            output = root / "shot_recipe_acceptance_not_for_release.mp4"
            made = subprocess.run([
                engine.ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=24:d=3",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source),
            ], capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            data = recipe_project(str(source), str(output), fps=24, duration=3)
            data["timeline"]["videoTracks"][0]["clips"][0]["start"] = 0
            validated = engine.validate(data, strict_media=True)
            self.assertTrue(validated.valid, [item.to_dict() for item in validated.issues])
            compiled = engine.compile(data, overwrite=True)
            self.assertEqual(compiled.summary["shotRecipes"]["status"], "PASS")
            rendered = engine.render(data, overwrite=True)
            self.assertTrue(output.is_file())
            self.assertEqual(rendered.manifest["shotRecipes"]["status"], "PASS")
            sidecar = Path(rendered.manifest["shotRecipes"]["sidecarPath"])
            self.assertTrue(sidecar.is_file())
            sidecar_value = json.loads(sidecar.read_text(encoding="utf-8"))
            materialized = sidecar_value["materializedTimeline"][0]
            self.assertEqual(materialized["recipeId"], "camera.slow_push_in")
            self.assertEqual(materialized["provenance"]["outputFps"], 24)
            self.assertEqual(materialized["resolvedRecipe"]["action"].keys(), {"setup", "contact", "result"})
            self.assertFalse(sidecar_value["platformMutationAuthorized"])


if __name__ == "__main__":
    unittest.main()
