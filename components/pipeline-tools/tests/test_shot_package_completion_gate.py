import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.shot_package_completion_gate import audit_shot_packages


SHA = {
    "canonical": "1" * 64,
    "manifest": "2" * 64,
    "prompt": "3" * 64,
    "first": "4" * 64,
    "character": "5" * 64,
    "wardrobe": "6" * 64,
    "scene": "7" * 64,
    "prop": "8" * 64,
    "audio": "9" * 64,
    "lip": "a" * 64,
    "qa": "b" * 64,
    "output": "c" * 64,
}


def package(*, dialogue=False):
    value = {
        "package_id": "E40-U01",
        "state": "COMPLETE",
        "canonical_binding": {
            "canonical_sha256": SHA["canonical"],
            "manifest_sha256": SHA["manifest"],
        },
        "prompt": {"status": "PRECOMPILED", "sha256": SHA["prompt"]},
        "generation": {"model": "seedance-2.0-fast", "status": "COMPLETED"},
        "first_frame": {"exact": True, "sha256": SHA["first"]},
        "ordered_references": [
            {"order": 1, "role": "FIRST_FRAME", "sha256": SHA["first"]},
            {"order": 2, "role": "CHARACTER", "sha256": SHA["character"]},
        ],
        "asset_bindings": {
            "characters": [{"asset_id": "CHENJI", "sha256": SHA["character"]}],
            "wardrobe": [
                {
                    "asset_id": "CHENJI-W01",
                    "character_id": "CHENJI",
                    "sha256": SHA["wardrobe"],
                }
            ],
            "scenes": [{"asset_id": "SCENE-A", "sha256": SHA["scene"]}],
            "props": [{"asset_id": "PROP-A", "sha256": SHA["prop"]}],
        },
        "dialogue": {"applicable": False},
        "qa": {
            "status": "ADMITTED",
            "receipt_sha256": SHA["qa"],
            "output_sha256": SHA["output"],
        },
        "output": {"sha256": SHA["output"], "duration_seconds": 4.25},
    }
    if dialogue:
        value["dialogue"] = {
            "applicable": True,
            "transport": "VISIBLE_EXACT_LINE",
            "audio": {"status": "PASS", "sha256": SHA["audio"]},
            "lip_sync": {"applicable": True, "status": "PASS", "qa_sha256": SHA["lip"]},
        }
    return value


def inventory(*packages):
    return {
        "schema": "backlotos.shot_package_inventory.v1",
        "episode": "E40",
        "canonical": {"sha256": SHA["canonical"]},
        "manifest": {
            "sha256": SHA["manifest"],
            "canonical_sha256": SHA["canonical"],
        },
        "packages": list(packages),
    }


class ShotPackageCompletionGateTests(unittest.TestCase):
    def test_complete_package_counts_real_throughput(self):
        result = audit_shot_packages(inventory(package()))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["packages"][0]["computed_state"], "COMPLETE")
        self.assertEqual(
            result["throughput"],
            {
                "completed_packages": 1,
                "admitted_video_seconds": 4.25,
                "assembly_ready": True,
                "precompile_only": 0,
            },
        )

    def test_declared_complete_cannot_override_precompile_only(self):
        value = package()
        value["generation"]["status"] = "NOT_SUBMITTED"
        value.pop("qa")
        value.pop("output")
        result = audit_shot_packages(inventory(value))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["packages"][0]["computed_state"], "PRECOMPILED")
        self.assertEqual(result["throughput"]["completed_packages"], 0)
        self.assertEqual(result["throughput"]["admitted_video_seconds"], 0.0)
        self.assertEqual(result["throughput"]["precompile_only"], 1)
        self.assertFalse(result["throughput"]["assembly_ready"])

    def test_generated_but_unadmitted_clip_is_in_progress_and_zero_seconds(self):
        value = package()
        value["qa"]["status"] = "PENDING"
        result = audit_shot_packages(inventory(value))
        self.assertEqual(result["packages"][0]["computed_state"], "IN_PROGRESS")
        self.assertEqual(result["throughput"]["completed_packages"], 0)
        self.assertEqual(result["throughput"]["admitted_video_seconds"], 0.0)
        self.assertEqual(result["throughput"]["precompile_only"], 0)

    def test_pro_bare_and_mini_models_fail_closed(self):
        for model in ("seedance-2.0-pro", "seedance-2.0", "seedance-2.0-mini"):
            with self.subTest(model=model):
                value = package()
                value["generation"]["model"] = model
                result = audit_shot_packages(inventory(value))
                self.assertEqual(result["packages"][0]["computed_state"], "BLOCKED")
                self.assertIn(
                    "NON_PRODUCTION_VIDEO_MODEL",
                    {row["code"] for row in result["packages"][0]["failures"]},
                )

    def test_reference_order_and_first_frame_binding_are_exact(self):
        value = package()
        value["ordered_references"][0]["order"] = 2
        value["ordered_references"][1]["order"] = 1
        value["ordered_references"][0]["sha256"] = "d" * 64
        result = audit_shot_packages(inventory(value))
        codes = {row["code"] for row in result["packages"][0]["failures"]}
        self.assertIn("REFERENCE_ORDER_NOT_CONTIGUOUS_FROM_ONE", codes)
        self.assertIn("ORDERED_FIRST_FRAME_SHA256_MISMATCH", codes)
        self.assertEqual(result["packages"][0]["computed_state"], "BLOCKED")

    def test_every_asset_category_and_wardrobe_owner_are_required(self):
        value = package()
        value["asset_bindings"]["props"] = []
        value["asset_bindings"]["wardrobe"][0]["character_id"] = "UNKNOWN"
        result = audit_shot_packages(inventory(value))
        codes = {row["code"] for row in result["packages"][0]["failures"]}
        self.assertIn("ASSET_BINDING_CATEGORY_MISSING_OR_EMPTY", codes)
        self.assertIn("WARDROBE_CHARACTER_BINDING_UNKNOWN", codes)

    def test_explicit_non_applicable_prop_category_is_allowed(self):
        value = package()
        value["asset_bindings"]["props"] = {
            "applicable": False,
            "items": [],
            "reason": "This reaction close-up has no visible or transferred prop.",
        }
        result = audit_shot_packages(inventory(value))
        self.assertEqual(result["status"], "PASS")

    def test_non_applicable_asset_category_requires_reason(self):
        value = package()
        value["asset_bindings"]["props"] = {"applicable": False, "items": []}
        result = audit_shot_packages(inventory(value))
        self.assertIn(
            "NON_APPLICABLE_ASSET_CATEGORY_REASON_MISSING",
            {row["code"] for row in result["packages"][0]["failures"]},
        )

    def test_dialogue_requires_audio_and_lip_sync_when_visible(self):
        value = package(dialogue=True)
        value["dialogue"]["audio"].pop("sha256")
        value["dialogue"]["lip_sync"]["status"] = "PENDING"
        result = audit_shot_packages(inventory(value))
        codes = {row["code"] for row in result["packages"][0]["failures"]}
        self.assertIn("DIALOGUE_AUDIO_SHA256_MISSING_OR_INVALID", codes)
        self.assertIn("LIP_SYNC_NOT_PASS", codes)
        self.assertEqual(result["throughput"]["admitted_video_seconds"], 0.0)

    def test_offscreen_dialogue_can_explicitly_waive_lip_sync(self):
        value = package(dialogue=True)
        value["dialogue"]["transport"] = "VOICEOVER"
        value["dialogue"]["lip_sync"] = {
            "applicable": False,
            "reason": "The bound line is offscreen narration with no visible speaking face.",
        }
        result = audit_shot_packages(inventory(value))
        self.assertEqual(result["status"], "PASS")

    def test_qa_must_admit_the_exact_output_sha(self):
        value = package()
        value["qa"]["output_sha256"] = "d" * 64
        result = audit_shot_packages(inventory(value))
        self.assertIn(
            "QA_OUTPUT_SHA256_MISMATCH",
            {row["code"] for row in result["packages"][0]["failures"]},
        )
        self.assertEqual(result["throughput"]["completed_packages"], 0)

    def test_all_packages_must_complete_before_assembly(self):
        complete = package()
        complete["package_id"] = "E40-U01"
        precompiled = package()
        precompiled["package_id"] = "E40-U02"
        precompiled["generation"]["status"] = "NOT_SUBMITTED"
        precompiled.pop("qa")
        precompiled.pop("output")
        result = audit_shot_packages(inventory(complete, precompiled))
        self.assertEqual(result["throughput"]["completed_packages"], 1)
        self.assertEqual(result["throughput"]["admitted_video_seconds"], 4.25)
        self.assertEqual(result["throughput"]["precompile_only"], 1)
        self.assertFalse(result["throughput"]["assembly_ready"])

    def test_manifest_must_bind_canonical_sha(self):
        payload = inventory(package())
        payload["manifest"]["canonical_sha256"] = "f" * 64
        result = audit_shot_packages(payload)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("MANIFEST_CANONICAL_SHA256_MISMATCH", {row["code"] for row in result["failures"]})

    def test_package_id_is_required_even_when_all_evidence_passes(self):
        value = package()
        value.pop("package_id")
        result = audit_shot_packages(inventory(value))
        self.assertEqual(result["packages"][0]["computed_state"], "BLOCKED")
        self.assertIn(
            "PACKAGE_ID_MISSING",
            {row["code"] for row in result["packages"][0]["failures"]},
        )

    def test_cli_writes_atomic_json_and_returns_two_on_invalid_json(self):
        gate = Path(__file__).resolve().parents[1] / "shot_package_completion_gate.py"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "bad.json"
            output = root / "report.json"
            source.write_text("{bad", encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(gate), "--input", str(source), "--output", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(process.returncode, 2)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "FAIL")
            self.assertFalse(report["throughput"]["assembly_ready"])
            self.assertEqual(report["failures"][0]["code"], "INPUT_JSON_INVALID")
            self.assertFalse(list(root.glob(f".{output.name}.*.tmp")))


if __name__ == "__main__":
    unittest.main()
