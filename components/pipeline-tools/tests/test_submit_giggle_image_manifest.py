import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.submit_giggle_image_manifest import submit_all, validate_anchor_count_gate_requirement


class SubmitGiggleImageManifestTest(unittest.TestCase):
    def test_video_unit_batch_requires_variable_anchor_gate(self):
        manifest = {"tasks": [{"video_unit_id": "E99-CW-U01"}]}
        with self.assertRaisesRegex(ValueError, "anchor count must be justified per unit"):
            validate_anchor_count_gate_requirement(
                manifest,
                [{"schema": "qingshan.some_other_gate.v1", "status": "PASS"}],
            )

    def test_video_unit_batch_accepts_variable_anchor_gate(self):
        manifest = {"tasks": [{"video_unit_id": "E99-CW-U01"}]}
        validate_anchor_count_gate_requirement(
            manifest,
            [{"schema": "qingshan.video_unit_anchor_count_gate.v1", "status": "PASS"}],
        )

    def test_partial_anchor_batch_requires_tracked_dependencies(self):
        gates = [{"schema": "qingshan.video_unit_anchor_count_gate.v1", "status": "PASS"}]
        manifest = {
            "consumer_contract": {"planned_anchor_count": 2},
            "tasks": [{"task_key": "U01-A1", "video_unit_id": "U01"}],
            "blocked_tasks": ["U01-A2"],
        }
        with self.assertRaisesRegex(ValueError, "declare every dependent anchor"):
            validate_anchor_count_gate_requirement(manifest, gates)

        manifest["dependent_anchor_specs"] = [
            {"task_key": "U01-A2", "depends_on_task_key": "U01-A1"}
        ]
        validate_anchor_count_gate_requirement(manifest, gates)

    def test_client_system_exit_is_an_isolated_zero_credit_failure(self):
        tasks = [
            {"task_key": "OK", "beat_id": "B1"},
            {"task_key": "TIMEOUT", "beat_id": "B2"},
        ]

        def fake_submit(task, receipt_dir):
            if task["task_key"] == "TIMEOUT":
                raise SystemExit("network timeout")
            return {"task_key": "OK", "task_id": "task-1", "status": "submitted"}

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "tools.submit_giggle_image_manifest.submit_one", side_effect=fake_submit
        ):
            results, failures = submit_all(tasks, Path(temp_dir), concurrency=2)

        self.assertEqual([row["task_key"] for row in results], ["OK"])
        self.assertEqual(failures[0]["task_key"], "TIMEOUT")
        self.assertEqual(failures[0]["credit"], 0)
        self.assertEqual(failures[0]["credit_status"], "FAILED_ZERO")


if __name__ == "__main__":
    unittest.main()
