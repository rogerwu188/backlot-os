import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from action_prompt_pipeline_cli import _read_prompt, compile_manifest


class ActionPromptPipelineCliTests(unittest.TestCase):
    def test_reads_repository_relative_prompt_before_manifest_relative_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_dir = root / "nested" / "manifests"
            manifest_dir.mkdir(parents=True)
            prompt = root / "workflow" / "prompts" / "action.txt"
            prompt.parent.mkdir(parents=True)
            prompt.write_text("repository-relative prompt", encoding="utf-8")
            prior = Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual(
                    _read_prompt({"prompt_file": "workflow/prompts/action.txt"}, manifest_dir),
                    "repository-relative prompt",
                )
            finally:
                os.chdir(prior)

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
