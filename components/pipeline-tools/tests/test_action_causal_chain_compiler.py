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


if __name__ == "__main__":
    unittest.main()
