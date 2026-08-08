import unittest

from tools.corpus_absorption_gate import validate_manifest


class CorpusAbsorptionGateTest(unittest.TestCase):
    def adapted(self, asset_id="asset-1"):
        return {
            "source_asset_id": asset_id,
            "source_url": f"https://example.test/{asset_id}",
            "source_type": "shot",
            "decision": "ADAPTED",
            "sha256": "a" * 64,
            "license_basis": "project-owner training authorization",
            "dataset_version": "hell-grind-v1",
            "adapter_version": "task2-1-shot-language-v1",
            "evaluation_receipt": "eval-1.json",
            "relations": ["character:hero", "scene:snowfield"],
        }

    def test_passes_only_when_every_asset_has_final_disposition(self):
        payload = {"expected_source_assets": 2, "records": [
            self.adapted(),
            {"source_asset_id": "asset-2", "source_url": "https://example.test/asset-2", "source_type": "media", "decision": "EXCLUDED", "exclusion_reason": "duplicate content SHA"},
        ]}
        result = validate_manifest(payload)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["adapted_assets"], 1)
        self.assertEqual(result["excluded_assets"], 1)

    def test_blocks_incomplete_and_pending_corpus(self):
        row = self.adapted()
        row["decision"] = "PENDING_QA"
        result = validate_manifest({"expected_source_assets": 3, "records": [row]})
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["pending_assets"], 1)
        self.assertEqual(result["missing_assets"], 2)

    def test_rejects_duplicate_source_identity(self):
        with self.assertRaisesRegex(ValueError, "duplicate source_asset_id"):
            validate_manifest({"expected_source_assets": 2, "records": [self.adapted(), self.adapted()]})


if __name__ == "__main__":
    unittest.main()
