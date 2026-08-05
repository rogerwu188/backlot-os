import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.seedance2_prompt_compiler import compile_prompt


class MultiKeyframeLongTakeTest(unittest.TestCase):
    def frame(self, path, timestamp, state, zone="room", transition=None):
        path.write_bytes(f"frame-{timestamp}".encode())
        row = {
            "timestamp_seconds": timestamp, "image_path": str(path),
            "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "state_token": state, "location_zone": zone,
            "actor_blocking": state, "action_event": state,
            "reference_role": state, "preserve_from_previous": "identity and location",
            "camera_side": zone, "camera_position": "fixed three-quarter position",
            "camera_facing": "toward the same aperture",
            "do_not_inherit": ["text", "watermark"],
            "actor_motion": {
                "lead": {"visible": True, "continuous_micro_action": "steps through the action",
                         "event_reaction": "shifts weight toward the aperture", "motion_cues": ["breath", "footfall"]},
                "witness": {"visible": True, "continuous_micro_action": "tracks the lead with the eyes",
                            "event_reaction": "recoils half a step from the impact", "motion_cues": ["blink", "weight shift"]},
            },
        }
        if transition is not None:
            row["transition_from_previous"] = transition
        return row

    def transition(self, kind="CONTINUOUS_ACTION", camera_from="room", camera_to="room"):
        return {
            "kind": kind, "teleport_allowed": False, "action_reset_allowed": False,
            "continuous_camera_path": "locked axis", "camera_axis_reset_allowed": False,
            "camera_from_side": camera_from, "camera_to_side": camera_to,
            "camera_travel_distance_m": 0, "camera_axis_change_degrees": 0,
        }

    def spec(self, keyframes):
        root = Path(keyframes[0]["image_path"]).parent
        library = root / "historical-library.json"
        library.write_text("{}")
        characters = []
        for index, actor in enumerate(("lead", "witness")):
            visual = root / f"{actor}-visual"
            voice = root / f"{actor}-voice"
            visual.write_bytes(f"visual-{actor}".encode())
            voice.write_bytes(f"voice-{actor}".encode())
            characters.append({
                "actor": actor,
                "canonical_character_brief": {
                    "source_locator": f"scene-{index}", "era": "historical test era", "age": "adult",
                    "social_role": f"role-{index}", "wardrobe": f"wardrobe-{index}",
                    "face": f"face-{index}", "hair": f"hair-{index}", "voice": f"voice-{index}",
                    "writer_completed_before_asset_generation": True,
                },
                "visual_reference": {"path": str(visual), "sha256": hashlib.sha256(visual.read_bytes()).hexdigest()},
                "voice_reference": {"path": str(voice), "sha256": hashlib.sha256(voice.read_bytes()).hexdigest()},
                "historical_uniqueness_audit": {
                    "status": "PASS", "nearest_character_id": f"old-{index}",
                    "face_similarity": 0.2, "wardrobe_similarity": 0.2, "voice_similarity": 0.2,
                },
            })
        return {
            "mode": "multi_keyframe_long_take", "duration_seconds": 15,
            "model": "seedance-2.0-pro", "resolution": "1080p", "real_time_1x": True,
            "camera_motion_policy": "MOTIVATED_TRACK_OR_LOCKED_AXIS_NO_SWAY_NO_ORBIT_NO_ROAM",
            "subject_and_identity_lock": "same people", "spatial_continuity_lock": "same breach",
            "actor_roster": ["lead", "witness"],
            "episode_character_registry": {
                "frozen_before_video_generation": True,
                "historical_library_manifest": {"path": str(library), "sha256": hashlib.sha256(library.read_bytes()).hexdigest()},
                "characters": characters,
                "pairwise_uniqueness_audit": [{
                    "actor_a": "lead", "actor_b": "witness",
                    "face_similarity": 0.2, "wardrobe_similarity": 0.2, "voice_similarity": 0.2,
                }],
            },
            "action_axis": "escape", "negative_constraints": ["slow motion"], "keyframes": keyframes,
        }

    def combat_contract(self, root):
        lead = root / "lead-identity"
        opponent = root / "opponent-identity"
        lead.write_bytes(b"lead")
        opponent.write_bytes(b"opponent")
        return {
            "participants": [
                {"actor": "lead", "role": "interceptor",
                 "independent_identity_reference": {"path": str(lead), "sha256": hashlib.sha256(lead.read_bytes()).hexdigest()},
                 "wardrobe_silhouette": "light fitted jacket", "face_geometry": "round jaw and wide brows",
                 "first_second_displacement": "steps left by half a metre and raises both forearms"},
                {"actor": "witness", "role": "intruder",
                 "independent_identity_reference": {"path": str(opponent), "sha256": hashlib.sha256(opponent.read_bytes()).hexdigest()},
                 "wardrobe_silhouette": "dark sleeveless work vest", "face_geometry": "long jaw and broken nose",
                 "first_second_displacement": "lands forward by one metre and turns the right shoulder"},
            ],
            "action_reference_video": {"url": "https://example.test/reference.mp4", "reference_scope": "CHOREOGRAPHY_TIMING_AND_BODY_MECHANICS_ONLY"},
            "beats": [
                {"start_seconds": 0, "end_seconds": 3, "initiator": "witness", "target": "lead", "action": "straight right punch", "contact_point": "raised left forearm", "force_direction": "forward and down", "footwork": "right step", "target_reaction": "absorbs the strike and shifts the left foot", "end_state": "forearms remain in contact"},
                {"start_seconds": 3, "end_seconds": 6, "initiator": "lead", "target": "witness", "action": "outside wrist turn", "contact_point": "right wrist", "force_direction": "clockwise toward the table", "footwork": "left pivot", "target_reaction": "torso turns and right elbow bends", "end_state": "intruder faces the table"},
                {"start_seconds": 6, "end_seconds": 9, "initiator": "witness", "target": "lead", "action": "left elbow escape", "contact_point": "lead right shoulder", "force_direction": "backward", "footwork": "rear cross-step", "target_reaction": "takes one recovery step", "end_state": "actors separate by one arm length"},
                {"start_seconds": 9, "end_seconds": 12, "initiator": "lead", "target": "witness", "action": "shoulder capture", "contact_point": "right shoulder and wrist", "force_direction": "down toward the table", "footwork": "right step behind the heel", "target_reaction": "knees bend and chest lowers", "end_state": "intruder is chest-down at table edge"},
                {"start_seconds": 12, "end_seconds": 15, "initiator": "lead", "target": "witness", "action": "two-point restraint", "contact_point": "right wrist and upper back", "force_direction": "down", "footwork": "stable staggered stance", "target_reaction": "stops struggling without changing identity", "end_state": "lead controls intruder"},
            ],
            "winner": "lead", "restrained_actor": "witness",
            "terminal_identity_hold": "lead remains standing and pins witness chest-down; their faces and wardrobes remain distinct",
        }

    def test_accepts_same_aperture_crossing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuous = self.transition()
            crossing = {
                **self.transition("SAME_APERTURE_CROSSING", "room", "street"),
                "aperture_id": "east-wall", "direction": "inside_to_outside",
                "camera_path_kind": "FOLLOW_THROUGH_SAME_APERTURE",
                "camera_crosses_with_subjects": True,
                "camera_path_aperture_id": "east-wall",
                "camera_travel_distance_m": 2, "camera_axis_change_degrees": 10,
            }
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "breach", transition=continuous), self.frame(root / "c", 15, "outside", "street", crossing)]
            prompt, manifest = compile_prompt(self.spec(frames))
            self.assertIn("@图片3", prompt)
            self.assertIn("LORA-SD2-001-REFERENCE-GEOMETRY-LEAK", prompt)
            self.assertIn("LORA-SD2-002-UNIQUE-PROP-GROUP-REACTION", prompt)
            self.assertIn("LORA-SD2-003-ADJACENT-CAMERA-TRAJECTORY", prompt)
            self.assertIn("逐人动作覆盖", prompt)
            self.assertIn("FULL_VISIBLE_ACTOR_MOTION_COVERAGE", manifest["gates"])
            self.assertIn("EPISODE_CHARACTER_ASSETS_FROZEN_AND_UNIQUE", manifest["gates"])
            self.assertEqual(manifest["route"], "/api/v1/generation/omni-video")
            applied = manifest["local_lora_memory"]["applied_sample_ids"]
            self.assertTrue({
                "LORA-SD2-001-REFERENCE-GEOMETRY-LEAK",
                "LORA-SD2-002-UNIQUE-PROP-GROUP-REACTION",
                "LORA-SD2-003-ADJACENT-CAMERA-TRAJECTORY",
                "LORA-SD2-010-DIALOGUE-MODE-CONTRACT-DRIFT",
            }.issubset(applied))

    def test_rejects_unbound_location_jump(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuous = self.transition()
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "breach", transition=continuous), self.frame(root / "c", 15, "outside", "street", continuous)]
            with self.assertRaisesRegex(ValueError, "SAME_APERTURE_CROSSING"):
                compile_prompt(self.spec(frames))

    def test_rejects_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuous = self.transition()
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=continuous), self.frame(root / "c", 15, "end", transition=continuous)]
            spec = self.spec(frames)
            spec["model"] = "seedance-2.0-fast"
            with self.assertRaisesRegex(ValueError, "seedance-2.0-pro"):
                compile_prompt(spec)

    def test_rejects_impossible_camera_axis_jump(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            impossible = self.transition()
            impossible["camera_axis_change_degrees"] = 180
            frames = [
                self.frame(root / "a", 0, "start"),
                self.frame(root / "b", 7, "middle", transition=impossible),
                self.frame(root / "c", 15, "end", transition=self.transition()),
            ]
            with self.assertRaisesRegex(ValueError, "camera axis change exceeds 90 degrees"):
                compile_prompt(self.spec(frames))

    def test_rejects_unreachable_camera_speed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            impossible = self.transition()
            impossible["camera_travel_distance_m"] = 20
            frames = [
                self.frame(root / "a", 0, "start"),
                self.frame(root / "b", 7, "middle", transition=impossible),
                self.frame(root / "c", 15, "end", transition=self.transition()),
            ]
            with self.assertRaisesRegex(ValueError, "camera path exceeds 2.5 m/s"):
                compile_prompt(self.spec(frames))

    def test_rejects_missing_visible_actor_motion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [
                self.frame(root / "a", 0, "start"),
                self.frame(root / "b", 7, "middle", transition=self.transition()),
                self.frame(root / "c", 15, "end", transition=self.transition()),
            ]
            del frames[1]["actor_motion"]["witness"]
            with self.assertRaisesRegex(ValueError, "cover the full actor roster"):
                compile_prompt(self.spec(frames))

    def test_rejects_static_position_language_as_motion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [
                self.frame(root / "a", 0, "start"),
                self.frame(root / "b", 7, "middle", transition=self.transition()),
                self.frame(root / "c", 15, "end", transition=self.transition()),
            ]
            frames[1]["actor_motion"]["witness"]["continuous_micro_action"] = "留在安全区静止"
            with self.assertRaisesRegex(ValueError, "static pose"):
                compile_prompt(self.spec(frames))

    def test_accepts_explicit_offscreen_actor_disposition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [
                self.frame(root / "a", 0, "start"),
                self.frame(root / "b", 7, "middle", transition=self.transition()),
                self.frame(root / "c", 15, "end", transition=self.transition()),
            ]
            frames[2]["actor_motion"]["witness"] = {
                "visible": False, "offscreen_reason": "exited through the same aperture during the prior interval",
            }
            prompt, manifest = compile_prompt(self.spec(frames))
            self.assertIn("已离开画面", prompt)
            self.assertFalse(manifest["keyframes"][2]["actor_motion"][1]["visible"])

    def test_combat_compiles_timed_beats_identity_refs_and_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            spec["combat_choreography_contract"] = self.combat_contract(root)
            prompt, manifest = compile_prompt(spec)
            self.assertIn("逐拍动作因果", prompt)
            self.assertIn("被制服者=witness", prompt)
            self.assertIn("@视频1只参考动作节拍", prompt)
            self.assertIn("COMBAT_IDENTITY_CHOREOGRAPHY_AND_OUTCOME", manifest["gates"])

    def test_combat_rejects_shared_identity_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            contract["participants"][1]["independent_identity_reference"] = contract["participants"][0]["independent_identity_reference"]
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "distinct identity references"):
                compile_prompt(spec)

    def test_rejects_character_missing_from_frozen_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            spec["episode_character_registry"]["characters"].pop()
            with self.assertRaisesRegex(ValueError, "exactly cover actor_roster"):
                compile_prompt(spec)

    def test_rejects_missing_writer_character_brief(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            del spec["episode_character_registry"]["characters"][1]["canonical_character_brief"]["wardrobe"]
            with self.assertRaisesRegex(ValueError, "canonical brief wardrobe is required"):
                compile_prompt(spec)

    def test_rejects_historically_similar_character_without_story_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            spec["episode_character_registry"]["characters"][1]["historical_uniqueness_audit"]["wardrobe_similarity"] = 0.95
            with self.assertRaisesRegex(ValueError, "too similar to historical library in wardrobe"):
                compile_prompt(spec)

    def test_single_actor_registry_does_not_require_a_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            spec["actor_roster"] = ["lead"]
            spec["episode_character_registry"]["characters"] = spec["episode_character_registry"]["characters"][:1]
            spec["episode_character_registry"]["pairwise_uniqueness_audit"] = []
            for frame in frames:
                del frame["actor_motion"]["witness"]
            prompt, manifest = compile_prompt(spec)
            self.assertIn("本集角色资产冻结", prompt)
            self.assertEqual(manifest["episode_character_registry"]["pairwise_audit_count"], 0)


if __name__ == "__main__":
    unittest.main()
