import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import cv2

import submit_giggle_video_manifest_v2 as submitter
from exact_first_frame_transport import IMAGE_TO_VIDEO_ENDPOINT, raw_rgb_sha256


class SubmitGiggleVideoManifestV2Tests(unittest.TestCase):
    def test_e50_sd2_deployed_entrypoint_requires_project_prompt_lineage_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = submitter.ROOT
            submitter.ROOT = root
            try:
                with self.assertRaisesRegex(ValueError, "project-owned paid prompt lineage gate"):
                    submitter.run_project_prompt_lineage_gate({
                        "task_key": "E50-VU-001",
                        "episode": "E50",
                        "model": "seedance-2.0-pro",
                    })
            finally:
                submitter.ROOT = previous

    def test_e50_sd2_deployed_entrypoint_executes_project_prompt_lineage_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / "tools"
            tools.mkdir()
            (tools / "submit_giggle_video_manifest_v2.py").write_text(
                "def validate_task(task):\n    raise ValueError('PROJECT_PROMPT_LINEAGE_GATE_CALLED')\n",
                encoding="utf-8",
            )
            previous = submitter.ROOT
            submitter.ROOT = root
            try:
                with self.assertRaisesRegex(ValueError, "PROJECT_PROMPT_LINEAGE_GATE_CALLED"):
                    submitter.run_project_prompt_lineage_gate({
                        "task_key": "E50-VU-001",
                        "episode": "E50",
                        "model": "seedance-2.0-pro",
                    })
            finally:
                submitter.ROOT = previous

    def test_project_hook_can_import_sibling_tool_when_installed_tools_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / "tools"
            tools.mkdir()
            (tools / "project_sibling.py").write_text(
                "def marker():\n    return 'PROJECT_SIBLING_RESOLVED'\n",
                encoding="utf-8",
            )
            (tools / "submit_giggle_video_manifest_v2.py").write_text(
                "from project_sibling import marker\n"
                "def validate_task(task):\n"
                "    raise ValueError(marker())\n",
                encoding="utf-8",
            )
            previous = submitter.ROOT
            submitter.ROOT = root
            try:
                with self.assertRaisesRegex(ValueError, "PROJECT_SIBLING_RESOLVED"):
                    submitter.run_project_prompt_lineage_gate({
                        "task_key": "E50-VU-001",
                        "episode": "E50",
                        "model": "seedance-2.0-pro",
                    })
            finally:
                submitter.ROOT = previous

    def test_pre_e50_task_does_not_require_project_specific_prompt_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = submitter.ROOT
            submitter.ROOT = Path(tmp)
            try:
                submitter.run_project_prompt_lineage_gate({
                    "task_key": "E49-VU-001",
                    "episode": "E49",
                    "model": "seedance-2.0-pro",
                })
            finally:
                submitter.ROOT = previous

    def test_precheck_uses_installed_style_project_root_without_post_or_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("人物呼吸，烛火自然摇曳，真实一倍速", encoding="utf-8")
            frame = root / "frame0.png"
            self.assertTrue(cv2.imwrite(str(frame), np.full((96, 54, 3), 70, dtype=np.uint8)))
            frame_sha = hashlib.sha256(frame.read_bytes()).hexdigest()
            gate = root / "machine-gate.json"
            gate.write_text(json.dumps({"schema": "fixture", "status": "PASS"}), encoding="utf-8")
            task = {
                "task_key": "U03-R2",
                "prompt_file": "prompt.txt",
                "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
                "reference_images": ["frame0.png"],
                "reference_sha256": [frame_sha],
                "reference_roles": ["EXACT_FIRST_FRAME"],
                "exact_first_frame_sha256": frame_sha,
                "model": "seedance-2.0-fast",
                "resolution": "720p",
                "duration_seconds": 4,
                "aspect_ratio": "9:16",
                "video_transport": {
                    "mode": "image_to_video_start_frame",
                    "endpoint": IMAGE_TO_VIDEO_ENDPOINT,
                    "start_frame_path": "frame0.png",
                    "start_frame_sha256": frame_sha,
                    "ordinary_images": [],
                },
                "frame0_authority_contract": {
                    "source_sha256": frame_sha,
                    "pre_encode_raw_rgb_sha256_required": True,
                    "raw_rgb_sha256": raw_rgb_sha256(frame),
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
            manifest = {
                "episode": "TEST",
                "provider": "giggle",
                "allowed_video_models": ["seedance-2.0-fast"],
                "machine_gate_reports": ["machine-gate.json"],
                "tasks": [task],
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            out = root / "precheck.json"
            argv = [
                "submit", "--project-root", str(root), "--manifest", "manifest.json",
                "--out", "precheck.json", "--precheck-only",
            ]
            with mock.patch("sys.argv", argv), mock.patch.object(submitter, "_request") as request:
                self.assertEqual(submitter.main(), 0)
            request.assert_not_called()
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["submitted"], 0)
            self.assertFalse((root / "workflow/tasks/giggle_video_submit_transactions").exists())


if __name__ == "__main__":
    unittest.main()
