import unittest

from action_causal_chain_compiler import compile_chain


def beat(key, entry, exit_state, phase):
    return {"task_key": key, "entry_state_token": entry, "exit_state_token": exit_state, "visible_phases": [phase], "real_time_1x": True}


class ActionCausalChainCompilerTests(unittest.TestCase):
    def test_serial_chain_preserves_parallelism_for_unrelated_work(self):
        result = compile_chain({"chain_id": "fight", "beats": [beat("a", "s0", "s1", "rise"), beat("b", "s1", "s2", "impact")]})
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["tasks"][1]["depends_on_task"], "a")
        self.assertEqual(result["global_scheduling_policy"]["unrelated_generation_and_qa"], "PARALLEL")

    def test_multiple_causal_phases_fail_closed(self):
        row = beat("a", "s0", "s1", "rise")
        row["visible_phases"] = ["rise", "impact"]
        result = compile_chain({"chain_id": "fight", "beats": [row]})
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failures"][0]["code"], "EXACTLY_ONE_VISIBLE_PHASE_REQUIRED")

    def test_broken_tail_state_fails_closed(self):
        result = compile_chain({"chain_id": "fight", "beats": [beat("a", "s0", "s1", "rise"), beat("b", "wrong", "s2", "impact")]})
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("ENTRY_DOES_NOT_MATCH_PREDECESSOR_EXIT", {row["code"] for row in result["failures"]})

    def test_compiler_exposes_optimizer_contracts(self):
        row = beat("a", "s0", "s1", "rise")
        row["prop_function"] = {"required_function_class": "落地环境冰屏"}
        row["scale_contract"] = {"required_relational_terms": ["两倍肩宽"], "frame_ratio_is_secondary_check": True}
        row["movement_lane_contract"] = {
            "lanes": [{"actor": "甲", "corridor": "左侧"}, {"actor": "乙", "corridor": "中部"}],
            "minimum_lateral_clearance": "一肩宽",
        }
        row["terminal_support_contract"] = {
            "result_hold_requires_stable_support": True,
            "required_support_points": ["双脚落地"],
        }
        task = compile_chain({"chain_id": "fight", "beats": [row]})["tasks"][0]
        self.assertEqual(task["action_prop_function_contract"]["required_function_class"], "落地环境冰屏")
        self.assertEqual(task["action_causality_contract"]["maximum_phases_per_shot"], 1)
        self.assertEqual(task["action_sequence_contract"]["entry_state_token"], "s0")
        self.assertTrue(task["performance_tempo_contract"]["real_time_1x"])
        self.assertEqual(task["action_scale_contract"]["required_relational_terms"], ["两倍肩宽"])
        self.assertEqual(len(task["action_movement_lane_contract"]["lanes"]), 2)
        self.assertEqual(task["action_terminal_support_contract"]["required_support_points"], ["双脚落地"])


if __name__ == "__main__":
    unittest.main()
