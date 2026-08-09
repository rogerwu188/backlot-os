import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import submit_giggle_image_manifest as submit_module
from tools.submit_giggle_image_manifest import (
    DuplicateSubmissionBlocked,
    atomic_json,
    classify_ambiguous_failures,
    configure_project_root,
    prior_submission_result,
    submission_fingerprint,
    submit_all,
    submit_one,
    transaction_path,
    validate_anchor_count_gate_requirement,
    validate_mask_transport,
    validate_reference_topology,
)


class SubmitGiggleImageManifestTest(unittest.TestCase):
    @staticmethod
    def write_precheck_manifest(root: Path, *, asset_role_only: bool) -> Path:
        prompt = root / "prompts" / "asset.txt"
        prompt.parent.mkdir(parents=True)
        source_action = "Baili keeps one red jade pendant and does not transfer it"
        prompt.write_text(source_action, encoding="utf-8")
        reference = root / "references" / ("character.bin" if asset_role_only else "scene.bin")
        reference.parent.mkdir(parents=True)
        reference.write_bytes(b"verified-reference")
        role = "character" if asset_role_only else "scene"
        entity_id = "CHAR-BAILI" if asset_role_only else "SCENE-HALL"
        binding = {
            "role": role,
            "entity_id": entity_id,
            "path": str(reference.relative_to(root)),
            "sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
            "qa_status": "PASS",
        }
        task = {
            "task_key": "AG02-ASSET" if asset_role_only else "U01-SHOT",
            "shot_id": "AG02" if asset_role_only else "U01",
            "tool_type": "image_generation",
            "prompt_file": str(prompt.relative_to(root)),
            "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
            "reference_images": [binding["path"]],
            "reference_bindings": [binding],
            "source_script_sha256": "a" * 64,
            "prompt_contract": {
                "schema": "qingshan.image_prompt_contract.v2",
                "status": "PASS",
                "shot_id": "AG02" if asset_role_only else "U01",
                "source_script_sha256": "a" * 64,
                "source_action": source_action,
                "source_action_sha256": hashlib.sha256(source_action.encode("utf-8")).hexdigest(),
                "visible_characters": ["CHAR-BAILI"] if asset_role_only else [],
                "reference_bindings": [binding],
                "spatial_continuity": {
                    "mode": "SAME_SPACE_CONTINUOUS",
                    "policy_source": "PER_UNIT_SCRIPT_CONTENT",
                    "anchor_scope": (
                        "REUSABLE_CHARACTER_ASSET_NO_SHOT_SCENE"
                        if asset_role_only
                        else "SHOT_SCENE"
                    ),
                },
            },
        }
        if asset_role_only:
            task.update(SubmitGiggleImageManifestTest.reusable_asset_task())
            task["task_key"] = "AG02-ASSET"
        gate = root / "qa" / "gate.json"
        gate.parent.mkdir(parents=True)
        gate.write_text(json.dumps({"schema": "test.gate.v1", "status": "PASS"}), encoding="utf-8")
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({
            "episode": "E40",
            "machine_gate_reports": [str(gate.relative_to(root))],
            "tasks": [task],
        }), encoding="utf-8")
        return manifest

    def test_external_project_root_runs_asset_precheck_with_zero_intents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_precheck_manifest(root, asset_role_only=True)
            out = root / "qa" / "precheck.json"
            argv = [
                "submit_giggle_image_manifest.py",
                "--project-root",
                str(root),
                "--manifest",
                "manifest.json",
                "--out",
                "qa/precheck.json",
                "--precheck-only",
            ]
            with patch.object(submit_module, "ROOT", submit_module.DEFAULT_ROOT), patch.object(
                sys, "argv", argv
            ):
                self.assertEqual(submit_module.main(), 0)

            report = json.loads(out.read_text(encoding="utf-8"))
            transactions = list(
                (root / "workflow/tasks/giggle_submit_transactions/E40").glob("*.json")
            )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["manifest"], "manifest.json")
            self.assertEqual(report["precheck_pass"], 1)
            self.assertEqual(report["submitted"], 0)
            self.assertEqual(transactions, [])

    def test_project_root_must_be_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            argv = [
                "submit_giggle_image_manifest.py",
                "--project-root",
                str(missing),
                "--manifest",
                "manifest.json",
                "--out",
                "precheck.json",
                "--precheck-only",
            ]
            with patch.object(
                submit_module, "ROOT", submit_module.DEFAULT_ROOT
            ), patch.object(sys, "argv", argv), self.assertRaisesRegex(
                SystemExit, "Project root is not an existing directory"
            ):
                submit_module.main()

    def test_default_root_preserves_ordinary_shot_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_precheck_manifest(root, asset_role_only=False)
            argv = [
                "submit_giggle_image_manifest.py",
                "--manifest",
                "manifest.json",
                "--out",
                "qa/precheck.json",
                "--precheck-only",
            ]
            with patch.object(submit_module, "DEFAULT_ROOT", root), patch.object(
                submit_module, "ROOT", root
            ), patch.object(sys, "argv", argv):
                self.assertEqual(submit_module.main(), 0)
            report = json.loads((root / "qa/precheck.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["manifest"], "manifest.json")

    def test_configure_project_root_default_is_unchanged(self):
        self.assertEqual(configure_project_root(None), submit_module.DEFAULT_ROOT)

    @staticmethod
    def reusable_asset_task():
        return {
            "task_key": "E40-AG02-REUSABLE-ASSET",
            "asset_role_only": True,
            "owner_count_state": [
                {
                    "item": "white veil",
                    "owner": "Baili",
                    "count": 1,
                    "transfer": "NONE",
                    "state": "ALWAYS_WORN",
                }
            ],
            "reusable_scope": {
                "authorized_units": ["U01", "U16"],
                "asset_role_only": True,
                "direct_shot_start_frame_use": False,
                "per_unit_unified_camera_light_rebuild_required": True,
                "original_image_human_qa_threshold": 80,
            },
        }

    @staticmethod
    def verified_character():
        return {
            "role": "character",
            "entity_id": "CHAR-BAILI",
            "path": "baili.jpg",
            "sha256": "b" * 64,
            "qa_status": "PASS",
        }

    def test_reusable_asset_allows_one_verified_character_and_no_scene(self):
        validate_reference_topology(self.reusable_asset_task(), [self.verified_character()])

    def test_ordinary_shot_still_requires_exactly_one_scene(self):
        validate_reference_topology(
            {"task_key": "SHOT"},
            [self.verified_character(), {"role": "scene", "entity_id": "SCENE-HALL"}],
        )
        with self.assertRaisesRegex(ValueError, "exactly one scene reference"):
            validate_reference_topology({"task_key": "SHOT"}, [self.verified_character()])

    def test_reusable_asset_rejects_scene_relabel_workaround(self):
        task = self.reusable_asset_task()
        with self.assertRaisesRegex(ValueError, "exactly one character reference"):
            validate_reference_topology(
                task,
                [{"role": "scene", "entity_id": "CHAR-BAILI", "qa_status": "PASS"}],
            )

    def test_reusable_asset_rejects_zero_or_multiple_characters(self):
        task = self.reusable_asset_task()
        with self.assertRaisesRegex(ValueError, "exactly one character reference"):
            validate_reference_topology(task, [])
        with self.assertRaisesRegex(ValueError, "exactly one character reference"):
            validate_reference_topology(
                task,
                [self.verified_character(), {**self.verified_character(), "entity_id": "CHAR-OTHER"}],
            )

    def test_reusable_asset_rejects_unverified_character(self):
        character = {**self.verified_character(), "qa_status": "PENDING"}
        with self.assertRaisesRegex(ValueError, "not verified"):
            validate_reference_topology(self.reusable_asset_task(), [character])

    def test_reusable_asset_rejects_direct_shot_start_frame_use(self):
        task = self.reusable_asset_task()
        task["direct_shot_start_frame_use"] = True
        with self.assertRaisesRegex(ValueError, "directly as a shot start frame"):
            validate_reference_topology(task, [self.verified_character()])

        task = self.reusable_asset_task()
        task["reusable_scope"]["direct_shot_start_frame_use"] = True
        with self.assertRaisesRegex(ValueError, "direct_shot_start_frame_use=false"):
            validate_reference_topology(task, [self.verified_character()])

    def test_reusable_asset_requires_owner_count_state_and_reusable_scope(self):
        task = self.reusable_asset_task()
        del task["owner_count_state"]
        with self.assertRaisesRegex(ValueError, "requires owner_count_state"):
            validate_reference_topology(task, [self.verified_character()])

        task = self.reusable_asset_task()
        del task["reusable_scope"]
        with self.assertRaisesRegex(ValueError, "requires reusable_scope"):
            validate_reference_topology(task, [self.verified_character()])

    def test_image_without_edit_mask_does_not_require_mask_transport(self):
        validate_mask_transport({"task_key": "PLAIN", "reference_bindings": []})

    def test_edit_mask_reference_cannot_claim_exact_mask_semantics(self):
        task = {
            "task_key": "MASKED",
            "reference_bindings": [{"role": "edit_mask"}],
        }
        with self.assertRaisesRegex(ValueError, "reference-only"):
            validate_mask_transport(task)

    def test_provider_native_mask_claim_fails_until_payload_support_exists(self):
        task = {
            "task_key": "MASKED",
            "reference_bindings": [{"role": "edit_mask"}],
            "mask_transport": {"mode": "provider_native"},
        }
        with self.assertRaisesRegex(ValueError, "not implemented"):
            validate_mask_transport(task)

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

    def test_submit_records_durable_intent_before_request_then_binds_task_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prompt = root / "prompt.txt"
            prompt.write_text("reusable character asset", encoding="utf-8")
            item = self.transaction_task()
            item.update({
                "prompt_file": str(prompt),
                "reference_images": [str(root / "character.jpg")],
            })
            transaction_dir = root / "transactions"

            def fake_request(_endpoint, _payload):
                intent = json.loads(transaction_path(transaction_dir, item).read_text())
                self.assertEqual(intent["state"], "INTENT_RECORDED")
                self.assertEqual(intent["retry_guard"], "DO_NOT_RESUBMIT_UNTIL_LEDGER_RECONCILED")
                self.assertIsNotNone(intent["attempt_id"])
                return {"data": {"task_id": "task-new"}}

            with patch("tools.submit_giggle_image_manifest.ROOT", root), patch(
                "tools.submit_giggle_image_manifest._image_list", return_value=["encoded"]
            ), patch("tools.submit_giggle_image_manifest._request", side_effect=fake_request):
                result = submit_one(item, root / "receipts", transaction_dir)

            transaction = json.loads(transaction_path(transaction_dir, item).read_text())
            self.assertEqual(transaction["state"], "SUBMITTED_TASK_ID_BOUND")
            self.assertEqual(transaction["task_id"], "task-new")
            self.assertEqual(result["task_id"], "task-new")

    def test_response_loss_preserves_quarantine_state_and_retry_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prompt = root / "prompt.txt"
            prompt.write_text("reusable character asset", encoding="utf-8")
            item = self.transaction_task()
            item.update({
                "prompt_file": str(prompt),
                "reference_images": [str(root / "character.jpg")],
            })
            transaction_dir = root / "transactions"

            with patch("tools.submit_giggle_image_manifest.ROOT", root), patch(
                "tools.submit_giggle_image_manifest._image_list", return_value=["encoded"]
            ), patch(
                "tools.submit_giggle_image_manifest._request",
                side_effect=TimeoutError("response lost"),
            ):
                with self.assertRaisesRegex(TimeoutError, "response lost"):
                    submit_one(item, root / "receipts", transaction_dir)

            transaction = json.loads(transaction_path(transaction_dir, item).read_text())
            self.assertEqual(transaction["state"], "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION")
            self.assertEqual(transaction["retry_guard"], "DO_NOT_RESUBMIT_UNTIL_LEDGER_RECONCILED")
            self.assertNotIn("task_id", transaction)

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
