import unittest
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from bgm_authenticity_gate import validate_bgm_contract, validate_bgm_cue_policy


class BgmAuthenticityContractTests(unittest.TestCase):
    def test_generated_bgm_contract_passes(self):
        project = {"metadata": {"bgm_contract": {
            "source_type": "GENERATED_EPISODE_BGM",
            "dialogue_duck_db": -8,
            "generation_task_id": "task-1",
            "generation_receipt": "workflow/tasks/bgm.json",
            "source_sha256": "a" * 64,
            "credit_evidence": "workflow/credit_reports/bgm.json",
        }}}
        self.assertEqual(validate_bgm_contract(project), [])

    def test_generated_bgm_ignores_unrelated_metadata(self):
        project = {"metadata": {"bgm_contract": {
            "source_type": "GENERATED_EPISODE_BGM",
            "dialogue_duck_db": -8,
            "generation_task_id": "task-1",
            "generation_receipt": "workflow/tasks/bgm.json",
            "source_sha256": "b" * 64,
            "credit_evidence": "workflow/credit_reports/bgm.json",
            "unrelated_metadata": None,
        }}}
        self.assertEqual(validate_bgm_contract(project), [])

    def test_library_fallback_needs_reason_and_similarity(self):
        project = {"metadata": {"bgm_contract": {
            "source_type": "LIBRARY_FALLBACK",
            "dialogue_duck_db": -8,
            "music_id": "MUSIC-1",
        }}}
        failures = validate_bgm_contract(project)
        self.assertIn("LIBRARY_BGM_FALLBACK_REASON_MISSING", failures)
        self.assertIn("LIBRARY_BGM_CROSS_EPISODE_SIMILARITY_NOT_PASS", failures)

    def test_missing_source_priority_contract_fails(self):
        self.assertEqual(validate_bgm_contract({}), ["BGM_SOURCE_PRIORITY_CONTRACT_MISSING"])

    def test_selective_cues_pass_with_ambience_gap_and_ducking(self):
        project = {
            "metadata": {"bgm_cue_policy": {"mode": "SELECTIVE_NARRATIVE_CUES", "ambience_only_required": True}},
            "timeline": {
                "videoTracks": [{"clips": [{"start": 0, "duration": 100}]}],
                "audioTracks": [{"id": "Audio.BGM", "clips": [
                    {"id": "opening", "start": 0, "duration": 20, "volume": 0.14,
                     "metadata": {"cue_role": "OPENING_MYSTERY", "dialogue_present": True}},
                    {"id": "action", "start": 40, "duration": 30, "volume": 0.30,
                     "metadata": {"cue_role": "ACTION_ESCALATION", "dialogue_present": False}},
                ]}],
            },
        }
        self.assertEqual(validate_bgm_cue_policy(project), [])

    def test_wall_to_wall_music_is_rejected(self):
        project = {
            "metadata": {"bgm_cue_policy": {"mode": "SELECTIVE_NARRATIVE_CUES", "ambience_only_required": True}},
            "timeline": {
                "videoTracks": [{"clips": [{"start": 0, "duration": 100}]}],
                "audioTracks": [{"id": "Audio.BGM", "clips": [
                    {"id": "wall", "start": 0, "duration": 100, "volume": 0.12,
                     "metadata": {"cue_role": "OPENING_MYSTERY", "dialogue_present": True}},
                ]}],
            },
        }
        failures = validate_bgm_cue_policy(project)
        self.assertIn("BGM_WALL_TO_WALL_COVERAGE_GT_85_PERCENT", failures)
        self.assertIn("BGM_AMBIENCE_ONLY_WINDOW_LT_8_SECONDS", failures)


if __name__ == "__main__":
    unittest.main()
