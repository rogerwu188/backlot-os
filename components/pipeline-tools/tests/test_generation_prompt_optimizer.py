import hashlib
import sys
import tempfile
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
    def environment_screen_task(self):
        task = action_task()
        task["action_prop_function_contract"] = {
            "required_function_class": "落地环境冰屏",
            "forbidden_function_classes": ["手持盾牌", "掌前护盾"],
            "required_prompt_terms": ["冰屏下缘与地板连续相接"],
            "forbidden_prompt_terms": ["小型透明冰盾", "四边都可见"],
        }
        task["action_causality_contract"] = {
            "visible_phases": ["冰屏从地面升起"],
            "maximum_phases_per_shot": 1,
            "required_prompt_terms": ["本镜不发生撞击"],
        }
        task["action_scale_contract"] = {
            "required_relational_terms": ["高度约到成年男子肩部", "宽度足以隔开一人和火墙"],
            "frame_ratio_is_secondary_check": True,
        }
        return task

    def lane_separated_task(self):
        task = action_task()
        task["action_movement_lane_contract"] = {
            "lanes": [
                {"actor": "陈迹", "corridor": "画面左侧后撤走廊"},
                {"actor": "守宅人", "corridor": "画面中部前冲走廊"},
            ],
            "minimum_lateral_clearance": "一个成年男子肩宽",
            "required_prompt_terms": ["两人轮廓完全分离"],
            "forbidden_prompt_terms": ["贴身擦过", "从背后穿过"],
        }
        return task

    def stable_terminal_task(self):
        task = action_task()
        task["action_terminal_support_contract"] = {
            "result_hold_requires_stable_support": True,
            "required_support_points": ["双脚落地"],
            "required_prompt_terms": ["双脚完整踩住木地板"],
            "forbidden_prompt_terms": ["单脚悬空保持到结尾"],
        }
        return task

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

    def test_environment_screen_function_and_relational_scale_pass(self):
        task = self.environment_screen_task()
        base = "冰屏下缘与地板连续相接，高度约到成年男子肩部，宽度足以隔开一人和火墙。本镜不发生撞击。"
        prompt, receipt = optimize_prompt(task, base)
        task["prompt_optimizer_receipt"] = receipt
        self.assertEqual(validate_batch([task], {"B02": prompt})["status"], "PASS")
        self.assertTrue({"PF-013", "PF-014", "PF-015"}.issubset(receipt["applied_failure_memory_rules"]))

    def test_handheld_tablet_rewrite_fails_closed(self):
        task = self.environment_screen_task()
        base = "冰屏下缘与地板连续相接，高度约到成年男子肩部，宽度足以隔开一人和火墙。本镜不发生撞击。小型透明冰盾，四边都可见。"
        prompt, receipt = optimize_prompt(task, base)
        task["prompt_optimizer_receipt"] = receipt
        failures = validate_batch([task], {"B02": prompt})["failures"]
        self.assertTrue(any(row["code"] == "PROP_FUNCTION_CLASS_REWRITTEN" for row in failures))

    def test_multiple_visible_causal_phases_fail_closed(self):
        task = self.environment_screen_task()
        task["action_causality_contract"]["visible_phases"] = ["冰屏升起", "守宅人撞击"]
        base = "冰屏下缘与地板连续相接，高度约到成年男子肩部，宽度足以隔开一人和火墙。本镜不发生撞击。"
        prompt, receipt = optimize_prompt(task, base)
        task["prompt_optimizer_receipt"] = receipt
        failures = validate_batch([task], {"B02": prompt})["failures"]
        self.assertTrue(any(row["code"] == "ACTION_PHASE_BUDGET_EXCEEDED" for row in failures))

    def test_non_intersecting_movement_lanes_pass(self):
        task = self.lane_separated_task()
        prompt, receipt = optimize_prompt(task, "两人轮廓完全分离")
        task["prompt_optimizer_receipt"] = receipt
        self.assertEqual(validate_batch([task], {"B02": prompt})["status"], "PASS")
        self.assertIn("PF-016", receipt["applied_failure_memory_rules"])

    def test_authored_body_overlap_fails_closed(self):
        task = self.lane_separated_task()
        prompt, receipt = optimize_prompt(task, "两人轮廓完全分离，守宅人从背后穿过陈迹")
        task["prompt_optimizer_receipt"] = receipt
        failures = validate_batch([task], {"B02": prompt})["failures"]
        self.assertTrue(any(row["code"] == "MOVEMENT_LANE_OVERLAP_AUTHORED" for row in failures))

    def test_stable_terminal_support_passes(self):
        task = self.stable_terminal_task()
        prompt, receipt = optimize_prompt(task, "双脚完整踩住木地板")
        task["prompt_optimizer_receipt"] = receipt
        self.assertEqual(validate_batch([task], {"B02": prompt})["status"], "PASS")
        self.assertIn("PF-017", receipt["applied_failure_memory_rules"])

    def test_suspended_terminal_pose_fails_closed(self):
        task = self.stable_terminal_task()
        prompt, receipt = optimize_prompt(task, "双脚完整踩住木地板，单脚悬空保持到结尾")
        task["prompt_optimizer_receipt"] = receipt
        failures = validate_batch([task], {"B02": prompt})["failures"]
        self.assertTrue(any(row["code"] == "SUSPENDED_TERMINAL_POSE_AUTHORED" for row in failures))

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

    def test_period_entity_material_contract_binds_prompt_and_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "paper_effigy.png"
            reference.write_bytes(b"period-correct-reference")
            task = action_task()
            task["period_entity_material_contract"] = {
                "status": "PASS_PRECOMPILED",
                "hard_fail_override": True,
                "required_prompt_terms": ["桑皮纸", "竹篾"],
                "required_negative_prompt_terms": ["禁止金属", "机器人"],
                "terminal_reference": str(reference),
                "terminal_reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
            }
            prompt, receipt = optimize_prompt(task, "桑皮纸包覆竹篾。禁止金属，禁止机器人。")
            task["prompt_optimizer_receipt"] = receipt
            self.assertEqual(validate_batch([task], {"B02": prompt})["status"], "PASS")
            broken = prompt.replace("竹篾", "木条")
            failures = validate_batch([task], {"B02": broken})["failures"]
            self.assertTrue(any(row["code"] == "PERIOD_ENTITY_POSITIVE_TERM_MISSING" for row in failures))

    def test_period_entity_material_contract_rejects_reference_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "paper_effigy.png"
            reference.write_bytes(b"period-correct-reference")
            task = action_task()
            task["period_entity_material_contract"] = {
                "status": "PASS_PRECOMPILED",
                "hard_fail_override": True,
                "required_prompt_terms": [],
                "required_negative_prompt_terms": [],
                "terminal_reference": str(reference),
                "terminal_reference_sha256": "0" * 64,
            }
            prompt, receipt = optimize_prompt(task, "基础提示词")
            task["prompt_optimizer_receipt"] = receipt
            failures = validate_batch([task], {"B02": prompt})["failures"]
            self.assertTrue(any(row["code"] == "PERIOD_ENTITY_REFERENCE_SHA_MISMATCH" for row in failures))


if __name__ == "__main__":
    unittest.main()
