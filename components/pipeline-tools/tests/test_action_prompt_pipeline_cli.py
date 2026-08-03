import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from action_prompt_pipeline_cli import compile_manifest


class ActionPromptPipelineCliTests(unittest.TestCase):
    def test_bundled_example_compiles_and_reads_prior_actions(self):
        source = TOOLS / "examples/action_prompt_pipeline/episode_action_batch.json"
        with tempfile.TemporaryDirectory() as tmp:
            report = compile_manifest(source, Path(tmp))
            self.assertEqual(report["status"], "PASS")
            compiled = json.loads((Path(tmp) / "compiled_manifest.json").read_text(encoding="utf-8"))
            second = compiled["tasks"][1]["prompt_optimizer_receipt"]
            self.assertEqual(second["prior_action_task_keys"], ["DEMO-A01"])
            self.assertIn("PF-012", second["applied_failure_memory_rules"])


if __name__ == "__main__":
    unittest.main()
