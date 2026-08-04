import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from generation_prompt_optimizer import optimize_prompt, validate_batch


def action_task():
    return {
        "task_key": "B02",
        "prompt_optimizer_required": True,
        "performance_tempo_contract": {
            "primary_action_complete_by_seconds": 1.5,
            "result_hold_seconds": 0.55,
        },
        "action_sequence_contract": {
            "entry_state_token": "ENTRY",
            "exit_state_token": "EXIT",
        },
        "action_spatial_feasibility_contract": {
            "collision_corridor": {"x_min": 0.42, "x_max": 0.62, "y_min": 0.30, "y_max": 0.70},
            "effect_geometry": {
                "label": "盾",
                "max_width_ratio": 0.16,
                "max_height_ratio": 0.32,
                "plane_orientation": "30_DEGREES_OBLIQUE",
                "depth_order": "BETWEEN_ACTORS",
            },
            "maximum_subject_occlusion_ratio": 0.20,
        },
    }


class GenerationPromptOptimizerTests(unittest.TestCase):
    def test_compiles_positive_spatial_geometry(self):
        prompt, receipt = optimize_prompt(action_task(), "基础提示词")
        self.assertIn("开放碰撞通道", prompt)
        self.assertIn("盾宽不超过画幅16%", prompt)
        self.assertIn("尾帧保留保护道具", prompt)
        self.assertIn("PF-011", receipt["applied_failure_memory_rules"])

    def test_is_idempotent(self):
        first, _ = optimize_prompt(action_task(), "基础提示词")
        second, receipt = optimize_prompt(action_task(), first)
        self.assertEqual(first, second)
        self.assertFalse(receipt["changed"])

    def test_gate_binds_receipt_to_final_prompt(self):
        task = action_task()
        prompt, receipt = optimize_prompt(task, "基础提示词")
        task["prompt_optimizer_receipt"] = receipt
        self.assertEqual(validate_batch([task], {"B02": prompt})["status"], "PASS")
        self.assertEqual(validate_batch([task], {"B02": prompt + "篡改"})["status"], "FAIL")

    def test_reads_all_prior_actions_and_blocks_duplicate_signature(self):
        first = action_task()
        first["task_key"] = "B01"
        first["performance_spec"] = {"motion_beats": [{"subject": "甲", "action": "撞击", "contact_point": "肩", "direction": "向左", "end_state": "退开"}]}
        first_prompt, first_receipt = optimize_prompt(first, "第一镜")
        first["prompt_optimizer_receipt"] = first_receipt
        second = action_task()
        second["performance_spec"] = first["performance_spec"]
        second_prompt, second_receipt = optimize_prompt(second, "第二镜", [first])
        second["prompt_optimizer_receipt"] = second_receipt
        self.assertIn("PF-012", second_receipt["applied_failure_memory_rules"])
        report = validate_batch([first, second], {"B01": first_prompt, "B02": second_prompt})
        self.assertTrue(any(row["code"] == "ACTION_VISUAL_DUPLICATES_PRIOR_SHOT" for row in report["failures"]))


if __name__ == "__main__":
    unittest.main()
