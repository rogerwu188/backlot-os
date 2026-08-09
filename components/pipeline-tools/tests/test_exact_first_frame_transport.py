import hashlib
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from exact_first_frame_post_harvest_gate import evaluate_arrays
from exact_first_frame_transport import (
    IMAGE_TO_VIDEO_ENDPOINT,
    build_provider_request,
    evaluate_task,
    raw_rgb_sha256,
    transport_fingerprint,
)


class ExactFirstFrameTransportTests(unittest.TestCase):
    def make_task(self, root: Path):
        image = root / "frame0.png"
        pixels = np.zeros((96, 54, 3), dtype=np.uint8)
        pixels[:, :, 0] = np.arange(54, dtype=np.uint8)
        pixels[:, :, 1] = np.arange(96, dtype=np.uint8)[:, None]
        Image.fromarray(pixels, "RGB").save(image)
        source_sha = hashlib.sha256(image.read_bytes()).hexdigest()
        return {
            "task_key": "U03-R2",
            "reference_images": ["frame0.png"],
            "reference_sha256": [source_sha],
            "reference_roles": ["EXACT_FIRST_FRAME"],
            "exact_first_frame_sha256": source_sha,
            "model": "seedance-2.0-fast",
            "resolution": "720p",
            "duration_seconds": 4,
            "aspect_ratio": "9:16",
            "video_transport": {
                "mode": "image_to_video_start_frame",
                "endpoint": IMAGE_TO_VIDEO_ENDPOINT,
                "start_frame_path": "frame0.png",
                "start_frame_sha256": source_sha,
                "ordinary_images": [],
            },
            "frame0_authority_contract": {
                "source_sha256": source_sha,
                "pre_encode_raw_rgb_sha256_required": True,
                "raw_rgb_sha256": raw_rgb_sha256(image),
            },
            "post_harvest_exact_frame_gate": {
                "required": True,
                "single_frame_prepend_allowed": False,
                "single_frame_replacement_allowed": False,
                "frame0_thresholds": {
                    "minimum_ssim": 0.98,
                    "maximum_mae": 3.0,
                    "maximum_phash_hamming": 3,
                },
                "frame0_to_frame1_continuity_required": True,
            },
        }

    def test_native_start_frame_contract_passes_and_builds_no_omni_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.make_task(root)
            report = evaluate_task(task, root=root)
            self.assertEqual(report["status"], "PASS", report)
            endpoint, payload = build_provider_request(
                task, prompt_text="move", root=root, encode_image=lambda path: {"encoded": path}
            )
            self.assertEqual(endpoint, IMAGE_TO_VIDEO_ENDPOINT)
            self.assertIn("start_frame", payload)
            self.assertNotIn("images", payload)

    def test_omni_reference_and_missing_authority_contract_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.make_task(root)
            task["video_transport"] = {"mode": "omni_images", "ordinary_images": ["frame0.png"]}
            task.pop("frame0_authority_contract")
            codes = {row["code"] for row in evaluate_task(task, root=root)["failures"]}
            self.assertIn("EXACT_FIRST_FRAME_OMNI_REFERENCE_FORBIDDEN", codes)
            self.assertIn("EXACT_FIRST_FRAME_ENDPOINT_MUST_BE_IMAGE_TO_VIDEO", codes)
            self.assertIn("FRAME0_AUTHORITY_CONTRACT_MISSING", codes)

    def test_fast_720p_and_no_prepend_or_replace_are_hard_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.make_task(root)
            task["model"] = "seedance-2.0-pro"
            task["resolution"] = "1080p"
            task["post_harvest_exact_frame_gate"]["single_frame_prepend_allowed"] = True
            task["post_harvest_exact_frame_gate"]["single_frame_replacement_allowed"] = True
            codes = {row["code"] for row in evaluate_task(task, root=root)["failures"]}
            self.assertIn("EXACT_FIRST_FRAME_REQUIRES_FAST_MODEL", codes)
            self.assertIn("EXACT_FIRST_FRAME_REQUIRES_720P", codes)
            self.assertIn("SINGLE_FRAME_PREPEND_MUST_BE_FORBIDDEN", codes)
            self.assertIn("SINGLE_FRAME_REPLACEMENT_MUST_BE_FORBIDDEN", codes)

    def test_transport_contract_is_bound_into_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = self.make_task(Path(tmp))
            before = transport_fingerprint(task)
            task["video_transport"]["endpoint"] = "/api/v1/generation/omni-video"
            self.assertNotEqual(before, transport_fingerprint(task))

    def test_post_harvest_gate_accepts_exact_frame0_with_continuous_motion(self):
        authority = np.zeros((320, 180, 3), dtype=np.uint8)
        for y in range(320):
            authority[y, :, :] = (y % 255, (2 * y) % 255, (3 * y) % 255)
        frames = [np.roll(authority, shift=index, axis=1) for index in range(13)]
        report = evaluate_arrays(authority, frames)
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(report["automatic_repair"], "FORBIDDEN_NO_PREPEND_NO_REPLACEMENT")

    def test_post_harvest_gate_rejects_wrong_frame0_and_flash_jump(self):
        authority = np.full((320, 180, 3), 64, dtype=np.uint8)
        frames = [np.full_like(authority, 220)] + [np.full_like(authority, 64) for _ in range(12)]
        report = evaluate_arrays(authority, frames)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["frame0_authority"]["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
