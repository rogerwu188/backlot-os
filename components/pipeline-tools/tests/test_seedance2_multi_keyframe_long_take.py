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
            "do_not_inherit": ["text", "watermark"],
        }
        if transition is not None:
            row["transition_from_previous"] = transition
        return row

    def spec(self, keyframes):
        return {
            "mode": "multi_keyframe_long_take", "duration_seconds": 15,
            "model": "seedance-2.0-pro", "resolution": "1080p", "real_time_1x": True,
            "camera_motion_policy": "MOTIVATED_TRACK_OR_LOCKED_AXIS_NO_SWAY_NO_ORBIT_NO_ROAM",
            "subject_and_identity_lock": "same people", "spatial_continuity_lock": "same breach",
            "action_axis": "escape", "negative_constraints": ["slow motion"], "keyframes": keyframes,
        }

    def test_accepts_same_aperture_crossing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuous = {"kind": "CONTINUOUS_ACTION", "teleport_allowed": False, "action_reset_allowed": False}
            crossing = {**continuous, "kind": "SAME_APERTURE_CROSSING", "aperture_id": "east-wall", "direction": "inside_to_outside"}
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "breach", transition=continuous), self.frame(root / "c", 15, "outside", "street", crossing)]
            prompt, manifest = compile_prompt(self.spec(frames))
            self.assertIn("@图片3", prompt)
            self.assertIn("LORA-SD2-001-REFERENCE-GEOMETRY-LEAK", prompt)
            self.assertIn("LORA-SD2-002-UNIQUE-PROP-GROUP-REACTION", prompt)
            self.assertEqual(manifest["route"], "/api/v1/generation/omni-video")
            self.assertEqual(manifest["local_lora_memory"]["applied_sample_ids"], [
                "LORA-SD2-001-REFERENCE-GEOMETRY-LEAK",
                "LORA-SD2-002-UNIQUE-PROP-GROUP-REACTION",
            ])

    def test_rejects_unbound_location_jump(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuous = {"kind": "CONTINUOUS_ACTION", "teleport_allowed": False, "action_reset_allowed": False}
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "breach", transition=continuous), self.frame(root / "c", 15, "outside", "street", continuous)]
            with self.assertRaisesRegex(ValueError, "SAME_APERTURE_CROSSING"):
                compile_prompt(self.spec(frames))

    def test_rejects_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuous = {"kind": "CONTINUOUS_ACTION", "teleport_allowed": False, "action_reset_allowed": False}
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=continuous), self.frame(root / "c", 15, "end", transition=continuous)]
            spec = self.spec(frames)
            spec["model"] = "seedance-2.0-fast"
            with self.assertRaisesRegex(ValueError, "seedance-2.0-pro"):
                compile_prompt(spec)


if __name__ == "__main__":
    unittest.main()
