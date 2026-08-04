import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from action_spatial_feasibility_gate import evaluate_batch


def task():
    return {
        "task_key": "B02",
        "requires_spatial_feasibility_gate": True,
        "action_spatial_feasibility_contract": {
            "entry_geometry_derived_from_start_frame": True,
            "entry_pose_compatible": True,
            "exit_geometry_planned": True,
            "exit_pose_compatible_with_next_shot": True,
            "exit_preserves_protected_props": True,
            "collision_corridor": {
                "x_min": 0.42, "x_max": 0.62, "y_min": 0.30, "y_max": 0.70,
                "clear_of_protected_props": True, "limb_path_clear": True,
            },
            "effect_geometry": {
                "max_width_ratio": 0.16, "max_height_ratio": 0.32,
                "plane_orientation": "30_DEGREES_OBLIQUE", "depth_order": "BETWEEN_ACTORS",
            },
            "maximum_subject_occlusion_ratio": 0.20,
            "first_contact_before_effect_feedback": True,
            "required_prompt_clauses": ["开放碰撞通道", "盾宽不超过画幅16%"],
        },
    }


class ActionSpatialFeasibilityGateTests(unittest.TestCase):
    def test_feasible_contact_corridor_passes(self):
        self.assertEqual(evaluate_batch([task()], {"B02": "开放碰撞通道；盾宽不超过画幅16%"})["status"], "PASS")

    def test_effect_larger_than_corridor_fails(self):
        value = task()
        value["action_spatial_feasibility_contract"]["effect_geometry"]["max_width_ratio"] = 0.30
        report = evaluate_batch([value], {"B02": "开放碰撞通道；盾宽不超过画幅16%"})
        self.assertTrue(any(row["code"] == "EFFECT_TOO_WIDE_FOR_COLLISION_CORRIDOR" for row in report["failures"]))

    def test_incompatible_entry_pose_fails(self):
        value = task()
        value["action_spatial_feasibility_contract"]["entry_pose_compatible"] = False
        report = evaluate_batch([value], {"B02": "开放碰撞通道；盾宽不超过画幅16%"})
        self.assertTrue(any(row["code"] == "ENTRY_POSE_INCOMPATIBLE_WITH_ACTION" for row in report["failures"]))

    def test_incompatible_exit_pose_fails(self):
        value = task()
        value["action_spatial_feasibility_contract"]["exit_pose_compatible_with_next_shot"] = False
        report = evaluate_batch([value], {"B02": "开放碰撞通道；盾宽不超过画幅16%"})
        self.assertTrue(any(row["code"] == "EXIT_POSE_INCOMPATIBLE_WITH_NEXT_SHOT" for row in report["failures"]))

    def test_missing_positive_geometry_prompt_clause_fails(self):
        report = evaluate_batch([task()], {"B02": "only negative constraints"})
        self.assertTrue(any(row["code"] == "SPATIAL_CONTRACT_NOT_COMPILED_INTO_PROMPT" for row in report["failures"]))


if __name__ == "__main__":
    unittest.main()
