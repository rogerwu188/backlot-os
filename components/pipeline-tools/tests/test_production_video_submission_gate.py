import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from production_video_submission_gate import evaluate_manifest


class ProductionVideoSubmissionGateTests(unittest.TestCase):
    def manifest(self, root: Path, *, action_unit=False, contract=None, duration=15):
        prompt = root / "prompt.txt"
        prompt.write_text("0.0秒押送位移；4.8秒拦截扣腕；9.4秒按住前臂；禁止慢动作", encoding="utf-8")
        task = {
            "task_key": "U01-R4",
            "prompt_file": "prompt.txt",
            "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
            "duration_seconds": duration,
            "action_unit": action_unit,
            "model": "seedance-2.0",
        }
        if contract is not None:
            task["performance_tempo_contract"] = contract
        return {"episode": "E39", "tasks": [task]}

    def test_current_manifest_cannot_reuse_historical_pass_to_bypass_action_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.manifest(root)
            manifest["machine_gate_reports"] = ["old-pass.json"]
            (root / "old-pass.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            report = evaluate_manifest(manifest, root=root, manifest_path=path)
            codes = {row["code"] for row in report["failures"]}
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("ACTION_UNIT_CLASSIFICATION_MISSING", codes)
            self.assertIn("ACTION_TEMPO_CONTRACT_MISSING", codes)

    def test_current_prompt_sha_is_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.manifest(root)
            (root / "prompt.txt").write_text("changed", encoding="utf-8")
            report = evaluate_manifest(manifest, root=root)
            self.assertIn("CURRENT_PROMPT_SHA_MISMATCH", {row["code"] for row in report["failures"]})

    def test_pro_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.manifest(root)
            manifest["tasks"][0]["model"] = "seedance-2.0-pro"
            report = evaluate_manifest(manifest, root=root)
            self.assertIn("STANDARD_SEEDANCE2_MODEL_REQUIRED", {row["code"] for row in report["failures"]})

    def test_atomic_real_time_task_passes(self):
        contract = {
            "playback_speed": "REAL_TIME_1X",
            "primary_action_complete_by_seconds": 1.2,
            "result_hold_seconds": 0.0,
            "atomic_action_windows": [
                {"start_seconds": 0.0, "end_seconds": 1.0, "action": "拦截"},
                {"start_seconds": 1.0, "end_seconds": 2.0, "action": "扣腕"},
                {"start_seconds": 2.0, "end_seconds": 3.2, "action": "制止"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = evaluate_manifest(self.manifest(root, action_unit=True, contract=contract, duration=4), root=root)
            self.assertEqual(report["status"], "PASS", report)


if __name__ == "__main__":
    unittest.main()
