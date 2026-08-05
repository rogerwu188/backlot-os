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
        return {
            "mode": "multi_keyframe_long_take", "duration_seconds": 15,
            "model": "seedance-2.0-pro", "resolution": "1080p", "real_time_1x": True,
            "camera_motion_policy": "MOTIVATED_TRACK_OR_LOCKED_AXIS_NO_SWAY_NO_ORBIT_NO_ROAM",
            "subject_and_identity_lock": "same people", "spatial_continuity_lock": "same breach",
            "actor_roster": ["lead", "witness"],
            "action_axis": "escape", "negative_constraints": ["slow motion"], "keyframes": keyframes,
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
            self.assertEqual(manifest["route"], "/api/v1/generation/omni-video")
            self.assertEqual(manifest["local_lora_memory"]["applied_sample_ids"], [
                "LORA-SD2-001-REFERENCE-GEOMETRY-LEAK",
                "LORA-SD2-002-UNIQUE-PROP-GROUP-REACTION",
                "LORA-SD2-003-ADJACENT-CAMERA-TRAJECTORY",
            ])

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


if __name__ == "__main__":
    unittest.main()
