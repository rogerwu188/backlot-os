import unittest

from action_direction_contract_gate import evaluate_batch


def task(**overrides):
    contract = {
        "entry_screen_side": "SCREEN_RIGHT",
        "travel_direction": "RIGHT_TO_LEFT",
        "recoil_direction": "LEFT_TO_RIGHT",
        "terminal_screen_side": "SCREEN_RIGHT",
        "contact_body_part": "LEFT_SHOULDER",
        "contact_target": "PALM_FRONT_ICE_BUCKLER",
    }
    contract.update(overrides)
    return {"task_key": "A02", "action_unit": True, "action_direction_contract": contract}


class ActionDirectionContractGateTest(unittest.TestCase):
    def test_accepts_consistent_lateral_recoil(self):
        self.assertEqual(evaluate_batch([task()])["status"], "PASS")

    def test_rejects_entry_side_contradiction(self):
        report = evaluate_batch([task(entry_screen_side="SCREEN_LEFT")])
        self.assertIn("TRAVEL_DIRECTION_ENTRY_SIDE_CONTRADICTION", {f["code"] for f in report["failures"]})

    def test_rejects_recoil_direction_contradiction(self):
        report = evaluate_batch([task(recoil_direction="RIGHT_TO_LEFT")])
        self.assertIn("RECOIL_DIRECTION_NOT_OPPOSITE_TRAVEL", {f["code"] for f in report["failures"]})

    def test_requires_exact_contact_body_part(self):
        report = evaluate_batch([task(contact_body_part="")])
        self.assertIn("ACTION_DIRECTION_FIELD_MISSING", {f["code"] for f in report["failures"]})


if __name__ == "__main__":
    unittest.main()
