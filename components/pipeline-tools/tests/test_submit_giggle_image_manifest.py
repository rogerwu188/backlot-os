import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.submit_giggle_image_manifest import (
    DuplicateSubmissionBlocked,
    atomic_json,
    classify_ambiguous_failures,
    prior_submission_result,
    submission_fingerprint,
    submit_all,
    transaction_path,
    validate_anchor_count_gate_requirement,
)


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

    def test_client_system_exit_is_isolated_pending_ledger_reconciliation(self):
        tasks = [
            {"task_key": "OK", "beat_id": "B1"},
            {"task_key": "TIMEOUT", "beat_id": "B2"},
        ]

        def fake_submit(task, receipt_dir, transaction_dir):
            if task["task_key"] == "TIMEOUT":
                raise SystemExit("network timeout")
            return {"task_key": "OK", "task_id": "task-1", "status": "submitted"}

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "tools.submit_giggle_image_manifest.submit_one", side_effect=fake_submit
        ):
            root = Path(temp_dir)
            results, failures = submit_all(tasks, root / "receipts", root / "transactions", concurrency=2)

        self.assertEqual([row["task_key"] for row in results], ["OK"])
        self.assertEqual(failures[0]["task_key"], "TIMEOUT")
        self.assertIsNone(failures[0]["credit"])
        self.assertEqual(failures[0]["credit_status"], "PENDING_LEDGER_RECONCILIATION")

    @staticmethod
    def transaction_task(task_key="E99-U01-A1-STILL-V1"):
        return {
            "task_key": task_key,
            "prompt_sha256": "a" * 64,
            "reference_bindings": [{"sha256": "b" * 64}],
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "2K",
        }

    def test_bound_task_id_is_reused_without_resubmit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = self.transaction_task()
            path = transaction_path(root, item)
            atomic_json(path, {
                "submission_fingerprint": submission_fingerprint(item),
                "state": "SUBMITTED_TASK_ID_BOUND",
                "task_id": "task-123",
                "receipt": "receipt.json",
            })
            result = prior_submission_result(item, root)
            self.assertEqual(result["task_id"], "task-123")
            self.assertTrue(result["recovered_from_transaction"])

    def test_charged_missing_task_id_blocks_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = self.transaction_task()
            path = transaction_path(root, item)
            atomic_json(path, {
                "submission_fingerprint": submission_fingerprint(item),
                "state": "CHARGED_TASK_ID_MISSING",
            })
            with self.assertRaises(DuplicateSubmissionBlocked):
                prior_submission_result(item, root)

    def test_zero_charge_timeout_becomes_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = self.transaction_task()
            path = transaction_path(root, item)
            atomic_json(path, {
                "submission_fingerprint": submission_fingerprint(item),
                "state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
            })
            failures = [{"task_key": item["task_key"], "transaction": str(path), "credit": None}]
            classify_ambiguous_failures(
                failures,
                known_submitted=3,
                matched_ledger_rows=3,
                transaction_dir=root,
            )
            self.assertEqual(failures[0]["credit_status"], "FAILED_ZERO_VERIFIED")
            self.assertEqual(json.loads(path.read_text())["state"], "NOT_CHARGED_RETRYABLE")

    def test_multiple_ambiguous_charges_quarantine_every_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failures = []
            for index in range(2):
                item = self.transaction_task(f"E99-U0{index + 1}-A1-STILL-V1")
                path = transaction_path(root, item)
                atomic_json(path, {
                    "submission_fingerprint": submission_fingerprint(item),
                    "state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
                })
                failures.append({"task_key": item["task_key"], "transaction": str(path), "credit": None})
            classify_ambiguous_failures(
                failures,
                known_submitted=4,
                matched_ledger_rows=5,
                transaction_dir=root,
            )
            self.assertTrue(all(row["credit_status"] == "CHARGE_STATE_UNRESOLVED_BATCH" for row in failures))


if __name__ == "__main__":
    unittest.main()
