import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "local_lora_memory_sync.py"
SPEC = importlib.util.spec_from_file_location("local_lora_memory_sync", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def sample(sample_id="LORA-TEST-001"):
    return {
        "schema": "backlotos.seedance_prompt_lora_training_sample.v1",
        "sample_id": sample_id, "status": "ADMITTED",
        "generation_mode": "multi_keyframe_long_take",
        "applicable_modes": ["multi_keyframe_long_take"],
        "failure_evidence": "redacted://failure", "failed_prompt_sha256": "a" * 64,
        "failed_asset_sha256": "b" * 64, "root_cause": "camera drift",
        "optimization": "lock the camera", "accepted_evidence": "redacted://accepted",
        "accepted_prompt_sha256": "c" * 64, "accepted_asset_sha256": "d" * 64,
        "compiler_guard_clause": "camera remains locked", "tags": ["camera"],
    }


class LocalLoraMemorySyncTests(unittest.TestCase):
    def test_merges_portable_sample_and_writes_content_addressed_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            source = root / "incoming.jsonl"
            source.write_text(json.dumps(sample(), ensure_ascii=False) + "\n", encoding="utf-8")
            result = MODULE.synchronize(source, root, push=False)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["sampleCount"], 1)
            manifest = json.loads((root / MODULE.MANIFEST_RELATIVE).read_text(encoding="utf-8"))
            self.assertEqual(manifest["dataset_sha256"], result["datasetSha256"])

    def test_rejects_private_evidence_path(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "incoming.jsonl"
            row = sample()
            row["failure_evidence"] = "/Users/person/private/frame.png"
            source.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "redacted://"):
                MODULE._load(source)

    def test_rejects_same_id_with_different_learning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            destination = root / MODULE.DATASET_RELATIVE
            destination.parent.mkdir(parents=True)
            destination.write_text(json.dumps(sample()) + "\n", encoding="utf-8")
            incoming = sample()
            incoming["optimization"] = "a conflicting rewrite"
            source = root / "incoming.jsonl"
            source.write_text(json.dumps(incoming) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "immutable sample_id conflict"):
                MODULE.synchronize(source, root, push=False)


if __name__ == "__main__":
    unittest.main()
