import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lora_memory_hub", ROOT / "lora_memory_hub.py")
HUB = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(HUB)


def sample(sample_id="HUB-001"):
    return {
        "schema": "backlotos.seedance_prompt_lora_training_sample.v1",
        "sample_id": sample_id, "status": "ADMITTED", "generation_mode": "multi_keyframe_long_take",
        "applicable_modes": ["multi_keyframe_long_take"], "failure_evidence": "redacted://failure",
        "failed_prompt_sha256": "a" * 64, "failed_asset_sha256": "b" * 64,
        "root_cause": "overpacked action", "optimization": "one causal event per long take",
        "accepted_evidence": "redacted://accepted", "accepted_prompt_sha256": "c" * 64,
        "accepted_asset_sha256": "d" * 64, "compiler_guard_clause": "one causal event", "tags": ["action"],
    }


class FakeStore:
    def __init__(self, pending):
        self.items = pending
        self.processed = None
    def pending(self):
        return self.items
    def mark_processed(self, keys, commit):
        self.processed = (keys, commit)


class LoraMemoryHubTests(unittest.TestCase):
    def test_health_state_exposes_failure_type_without_secret_message(self):
        HUB.update_hub_state(status="RETRY_PENDING", error=RuntimeError("credential-value"))
        state = HUB.hub_state()
        self.assertEqual(state["lastStatus"], "RETRY_PENDING")
        self.assertEqual(state["lastErrorType"], "RuntimeError")
        self.assertNotIn("credential-value", json.dumps(state))

    def test_canonical_submission_rejects_private_path(self):
        row = sample()
        row["failure_evidence"] = "/private/evidence.png"
        with self.assertRaisesRegex(ValueError, "redacted://"):
            HUB.canonical_submission({"schema": "backlotos.lora_memory_submission.v1", "samples": [row]})

    def test_third_party_sample_without_explicit_training_rights_is_rejected(self):
        row = sample()
        row.update({
            "source_kind": "third_party",
            "source_url_sha256": "e" * 64,
            "rights_basis": "publicly_viewable",
            "content_policy": "licensed_training_material",
        })
        with self.assertRaisesRegex(ValueError, "explicit machine-learning training license"):
            HUB.canonical_submission({"schema": "backlotos.lora_memory_submission.v1", "samples": [row]})

    def test_abstracted_third_party_rule_with_explicit_rights_is_admitted(self):
        row = sample()
        row.update({
            "source_kind": "third_party",
            "source_url_sha256": "e" * 64,
            "rights_basis": "explicit_machine_learning_training_license",
            "content_policy": "abstracted_rule_only",
        })
        body, _ = HUB.canonical_submission({"schema": "backlotos.lora_memory_submission.v1", "samples": [row]})
        self.assertIn(b"abstracted_rule_only", body)

    def test_s3_objects_merge_once_then_publish_from_hub(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "repo"
            remote = Path(directory) / "remote.git"
            subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
            subprocess.run(["git", "clone", "-q", str(remote), str(checkout)], check=True)
            subprocess.run(["git", "config", "user.name", "Hub"], cwd=checkout, check=True)
            subprocess.run(["git", "config", "user.email", "hub@example.invalid"], cwd=checkout, check=True)
            (checkout / "README").write_text("hub\n")
            subprocess.run(["git", "add", "README"], cwd=checkout, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=checkout, check=True)
            subprocess.run(["git", "push", "-qu", "origin", "HEAD"], cwd=checkout, check=True)
            bodies = []
            for row in (sample("HUB-001"), sample("HUB-002")):
                body, digest = HUB.canonical_submission({"schema": "backlotos.lora_memory_submission.v1", "samples": [row]})
                bodies.append((f"inbox/{digest}.jsonl", body))
            store = FakeStore(bodies)
            result = HUB.converge_once(store, checkout)
            self.assertEqual(result["sampleCount"], 2)
            self.assertEqual(store.processed[0], [item[0] for item in bodies])


if __name__ == "__main__":
    unittest.main()
