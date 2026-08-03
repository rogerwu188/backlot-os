import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from action_sequence_continuity_gate import evaluate_batch as continuity_gate
from camera_motion_sequence_gate import evaluate_sequence as camera_gate
from generation_dependency_topology_gate import evaluate_batch as topology_gate
from performance_tempo_gate import evaluate_batch as tempo_gate


def action(key, index, entry, exit_state, predecessor=None):
    task = {
        "task_key": key,
        "action_unit": True,
        "duration_seconds": 4,
        "generation_schedule_mode": "TAIL_CHAINED_SERIAL",
        "dependencies_ready": index == 1,
        "camera_motion_contract": {"family": "fixed"},
        "performance_tempo_contract": {"playback_speed": "REAL_TIME_1X", "primary_action_complete_by_seconds": 1.5, "result_hold_seconds": 0.55},
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

    def test_slow_and_hidden_event_fail(self):
        tasks = [action("A1", 1, "S0", "S1"), action("A2", 2, "HIDDEN", "S2", "A1")]
        tasks[1]["duration_seconds"] = 6
        self.assertEqual(continuity_gate(tasks)["status"], "FAIL")
        self.assertEqual(tempo_gate(tasks)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
