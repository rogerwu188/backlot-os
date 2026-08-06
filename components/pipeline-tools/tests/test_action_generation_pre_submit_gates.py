import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from action_sequence_continuity_gate import evaluate_batch as continuity_gate
from camera_motion_sequence_gate import evaluate_sequence as camera_gate
from generation_dependency_topology_gate import evaluate_batch as topology_gate
from performance_tempo_gate import evaluate_batch as tempo_gate
from authored_action_window_gate import evaluate_batch as authored_window_gate


def action(key, index, entry, exit_state, predecessor=None):
    task = {
        "task_key": key,
        "action_unit": True,
        "duration_seconds": 4,
        "generation_schedule_mode": "TAIL_CHAINED_SERIAL",
        "dependencies_ready": index == 1,
        "camera_motion_contract": {"family": "fixed"},
        "performance_tempo_contract": {
            "playback_speed": "REAL_TIME_1X",
            "primary_action_complete_by_seconds": 1.5,
            "result_hold_seconds": 0.55,
            "atomic_action_windows": [
                {"action": "one contact", "start_seconds": 0.0, "end_seconds": 1.5},
            ],
        },
        "assembly_window_contract": {"trim_start_seconds": 0.0, "trim_end_seconds": 2.0, "preserve_native_speed": True, "duplicate_hold_policy": "DROP_ONLY_DUPLICATE_TAIL_FRAMES", "provider_tail_disposition": "DISCARD_UNAUTHORED_TAIL"},
        "performance_spec": {"motion_beats": [{"action": "one contact"}]},
        "action_sequence_contract": {"sequence_index": index, "entry_state_token": entry, "exit_state_token": exit_state, "predecessor_tail_frame_ref": f"tails/{index - 1}.jpg" if index > 1 else None},
    }
    if predecessor:
        task["depends_on_task"] = predecessor
    return task


class ActionGenerationPreSubmitGateTests(unittest.TestCase):
    def test_tail_chain_passes_without_serializing_sibling(self):
        tasks = [action("A1", 1, "S0", "S1"), action("A2", 2, "S1", "S2", "A1")]
        tasks.append({"task_key": "D1", "generation_schedule_mode": "INDEPENDENT_PARALLEL"})
        self.assertEqual(continuity_gate(tasks)["status"], "PASS")
        self.assertEqual(topology_gate(tasks)["status"], "PASS")
        self.assertEqual(tempo_gate(tasks)["status"], "PASS")
        self.assertEqual(camera_gate(tasks)["status"], "PASS")
        self.assertEqual(authored_window_gate(tasks)["status"], "PASS")

    def test_slow_and_hidden_event_fail(self):
        tasks = [action("A1", 1, "S0", "S1"), action("A2", 2, "HIDDEN", "S2", "A1")]
        tasks[1]["duration_seconds"] = 6
        self.assertEqual(continuity_gate(tasks)["status"], "FAIL")
        self.assertEqual(tempo_gate(tasks)["status"], "FAIL")

    def test_action_prompt_cannot_bypass_tempo_gate_by_omitting_action_flag(self):
        task = {
            "task_key": "U06",
            "duration_seconds": 10,
            "prompt": "0-2s intruder completes landing; 2-6s advances; 6-10s actor intercepts the lunge",
        }
        failures = tempo_gate([task])["failures"]
        codes = {row["code"] for row in failures}
        self.assertIn("ACTION_UNIT_CLASSIFICATION_MISSING", codes)
        self.assertIn("ACTION_TEMPO_CONTRACT_MISSING", codes)

    def test_fight_beats_reject_delayed_onset_and_stretched_atomic_motion(self):
        task = action("F1", 1, "S0", "S1")
        task["shot_purpose"] = "fight"
        task["performance_tempo_contract"]["atomic_action_windows"] = [
            {"action": "landing", "start_seconds": 0.75, "end_seconds": 2.25},
        ]
        failures = tempo_gate([task])["failures"]
        codes = {row["code"] for row in failures}
        self.assertIn("FIGHT_ACTION_ONSET_TOO_LATE", codes)
        self.assertIn("ATOMIC_ACTION_WINDOW_TOO_LONG", codes)

    def test_missing_or_overlong_assembly_window_fails(self):
        task = action("A1", 1, "S0", "S1")
        task.pop("assembly_window_contract")
        self.assertEqual(authored_window_gate([task])["status"], "FAIL")
        task = action("A1", 1, "S0", "S1")
        task["assembly_window_contract"]["trim_end_seconds"] = 4.0
        self.assertEqual(authored_window_gate([task])["status"], "FAIL")

    def test_speed_change_and_retained_provider_tail_fail(self):
        task = action("A1", 1, "S0", "S1")
        task["assembly_window_contract"]["preserve_native_speed"] = False
        task["assembly_window_contract"]["provider_tail_disposition"] = "KEEP"
        failures = authored_window_gate([task])["failures"]
        self.assertIn("ACTION_ASSEMBLY_SPEED_CHANGE_FORBIDDEN", {row["code"] for row in failures})
        self.assertIn("UNAUTHORED_PROVIDER_TAIL_NOT_DISCARDED", {row["code"] for row in failures})

    def test_long_dialogue_requires_fixed_motivated_hard_cut(self):
        dialogue = {"task_key": "D1", "duration_seconds": 6, "shot_purpose": "DIALOGUE", "camera_motion_contract": {"family": "fixed"}}
        self.assertEqual(camera_gate([dialogue])["status"], "FAIL")
        dialogue["composition_change_contract"] = {"mode": "FIXED_HARD_CUT", "cut_at_seconds": 3.0}
        self.assertEqual(camera_gate([dialogue])["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
