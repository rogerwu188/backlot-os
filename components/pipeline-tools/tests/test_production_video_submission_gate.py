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
            "model": "seedance-2.0-fast",
        }
        if contract is not None:
            task["performance_tempo_contract"] = contract
        return {"episode": "E39", "tasks": [task]}

    def evaluate(self, manifest, root, *, manifest_path=None, supported_models=None):
        registry = root / "provider-video-capabilities.json"
        registry.write_text(json.dumps({
            "schema": "backlotos.provider_video_capabilities.v1",
            "providers": {
                "giggle": {
                    "status": "TEST_FIXTURE",
                    "supported_models": supported_models or ["seedance-2.0-fast"],
                }
            },
        }), encoding="utf-8")
        return evaluate_manifest(
            manifest,
            root=root,
            manifest_path=manifest_path,
            capability_registry_path=registry,
        )

    def test_current_manifest_cannot_reuse_historical_pass_to_bypass_action_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.manifest(root)
            manifest["machine_gate_reports"] = ["old-pass.json"]
            (root / "old-pass.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            report = self.evaluate(manifest, root, manifest_path=path)
            codes = {row["code"] for row in report["failures"]}
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("ACTION_UNIT_CLASSIFICATION_MISSING", codes)
            self.assertIn("ACTION_TEMPO_CONTRACT_MISSING", codes)

    def test_current_prompt_sha_is_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.manifest(root)
            (root / "prompt.txt").write_text("changed", encoding="utf-8")
            report = self.evaluate(manifest, root)
            self.assertIn("CURRENT_PROMPT_SHA_MISMATCH", {row["code"] for row in report["failures"]})

    def test_pro_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.manifest(root)
            manifest["tasks"][0]["model"] = "seedance-2.0-pro"
            report = self.evaluate(manifest, root)
            self.assertIn("TASK_MODEL_OUTSIDE_PRODUCTION_ALLOWLIST", {row["code"] for row in report["failures"]})

    def test_manifest_cannot_expand_production_policy_to_pro(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.manifest(root)
            manifest["allowed_video_models"] = ["seedance-2.0-fast", "seedance-2.0-pro"]
            report = self.evaluate(manifest, root, supported_models=["seedance-2.0-fast", "seedance-2.0-pro"])
            self.assertIn(
                "PRODUCTION_MODEL_POLICY_EXPANSION_FORBIDDEN",
                {row["code"] for row in report["failures"]},
            )

    def test_fast_only_manifest_passes_provider_model_gate(self):
        contract = {
            "playback_speed": "REAL_TIME_1X",
            "primary_action_complete_by_seconds": 1.2,
            "result_hold_seconds": 0.0,
            "atomic_action_windows": [
                {"start_seconds": 0.0, "end_seconds": 1.0, "action": "拦截"},
                {"start_seconds": 1.0, "end_seconds": 2.0, "action": "扣腕"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.manifest(root, action_unit=True, contract=contract, duration=2)
            manifest["allowed_video_models"] = ["seedance-2.0-fast"]
            report = self.evaluate(manifest, root, supported_models=["seedance-2.0-fast", "seedance-2.0-pro"])
            self.assertEqual(report["status"], "PASS", report)

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
            report = self.evaluate(self.manifest(root, action_unit=True, contract=contract, duration=4), root)
            self.assertEqual(report["status"], "PASS", report)

    def test_fast_but_incoherent_combat_is_rejected(self):
        contract = {
            "playback_speed": "REAL_TIME_1X",
            "primary_action_complete_by_seconds": 1.2,
            "result_hold_seconds": 0.0,
            "atomic_action_windows": [
                {"start_seconds": 0.0, "end_seconds": 1.0, "action": "攻击"},
                {"start_seconds": 1.0, "end_seconds": 2.0, "action": "防守"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.manifest(root, action_unit=True, contract=contract, duration=2)
            prompt = root / "prompt.txt"
            prompt.write_text("两人打斗，动作很快但随机交换招式", encoding="utf-8")
            manifest["tasks"][0]["prompt_sha256"] = hashlib.sha256(prompt.read_bytes()).hexdigest()
            report = self.evaluate(manifest, root)
            self.assertIn("COMBAT_CHOREOGRAPHY_CONTRACT_MISSING", {row["code"] for row in report["failures"]})

    def test_combat_requires_complete_causal_beats_and_terminal_result(self):
        contract = {
            "playback_speed": "REAL_TIME_1X",
            "primary_action_complete_by_seconds": 1.2,
            "result_hold_seconds": 0.0,
            "atomic_action_windows": [
                {"start_seconds": 0.0, "end_seconds": 1.0, "action": "攻击"},
                {"start_seconds": 1.0, "end_seconds": 2.0, "action": "防守"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.manifest(root, action_unit=True, contract=contract, duration=2)
            prompt = root / "prompt.txt"
            prompt.write_text("两人打斗，进攻后防守", encoding="utf-8")
            manifest["tasks"][0]["prompt_sha256"] = hashlib.sha256(prompt.read_bytes()).hexdigest()
            manifest["tasks"][0]["combat_choreography_contract"] = {
                "initiator": "甲", "objective": "夺刀", "spatial_axis": "甲左乙右",
                "causal_beats": [{"attack_intent": "甲刺", "defense_response": "乙格挡", "visible_consequence": "刀偏离", "end_state": "乙扣腕"}],
                "terminal_state": {"winner": "乙", "loser": "甲", "physical_result": "甲被按住且刀落地"},
            }
            report = self.evaluate(manifest, root)
            self.assertEqual(report["status"], "PASS", report)

    def test_provider_allowed_model_intersection_must_exist_before_submit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.manifest(root)
            report = self.evaluate(
                manifest,
                root,
                supported_models=["seedance-2.0-pro"],
            )
            codes = {row["code"] for row in report["failures"]}
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("PROVIDER_ALLOWED_MODEL_INTERSECTION_EMPTY", codes)
            self.assertIn("TASK_MODEL_UNSUPPORTED_BY_PROVIDER", codes)

    def test_bundled_giggle_registry_accepts_fast_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = evaluate_manifest(self.manifest(root), root=root)
            capability = report["provider_capability"]
            self.assertEqual(capability["provider"], "giggle")
            self.assertEqual(capability["allowed_supported_intersection"], ["seedance-2.0-fast"])
            self.assertEqual(capability["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
