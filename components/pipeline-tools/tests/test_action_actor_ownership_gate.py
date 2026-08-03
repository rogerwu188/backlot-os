import unittest

from action_actor_ownership_gate import evaluate_batch


def task(**overrides):
    item = {
        "task_key": "B03",
        "action_unit": True,
        "requires_actor_ownership_lock": True,
        "performance_spec": {"motion_beats": [{"subject": "云羊与纸人"}]},
        "action_actor_ownership_contract": {
            "ability_owner": "云羊",
            "inherited_foreground_actor": "陈迹",
            "forbidden_foreground_actions": ["触碰纸片", "施法"],
            "visible_origin_required": True,
            "required_prompt_clauses": ["只有云羊", "陈迹不得触碰纸片"],
        },
    }
    item.update(overrides)
    return item


class ActionActorOwnershipGateTest(unittest.TestCase):
    def test_accepts_complete_owner_change_lock(self):
        report = evaluate_batch([task()], {"B03": "只有云羊能够点纸成兵，陈迹不得触碰纸片。"})
        self.assertEqual(report["status"], "PASS")

    def test_rejects_generic_motion_subject(self):
        item = task(performance_spec={"motion_beats": [{"subject": "本镜动作主体"}]})
        report = evaluate_batch([item], {"B03": "只有云羊能够点纸成兵，陈迹不得触碰纸片。"})
        self.assertIn("ACTION_SUBJECT_GENERIC", {row["code"] for row in report["failures"]})

    def test_rejects_missing_prompt_clause(self):
        report = evaluate_batch([task()], {"B03": "云羊点纸成兵。"})
        self.assertIn("ACTOR_OWNERSHIP_PROMPT_CLAUSE_MISSING", {row["code"] for row in report["failures"]})

    def test_rejects_owner_equal_to_inherited_actor(self):
        item = task()
        item["action_actor_ownership_contract"]["ability_owner"] = "陈迹"
        report = evaluate_batch([item], {"B03": "只有云羊能够点纸成兵，陈迹不得触碰纸片。"})
        self.assertIn("OWNER_CHANGE_LOCK_WITHOUT_ACTOR_CHANGE", {row["code"] for row in report["failures"]})


if __name__ == "__main__":
    unittest.main()
