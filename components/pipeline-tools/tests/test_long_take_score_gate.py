import unittest

from tools.long_take_score_gate import adjudicate


class LongTakeScoreGateTest(unittest.TestCase):
    def test_at_60_is_retained(self):
        result = adjudicate(60)
        self.assertEqual(result["decision"], "PASS")
        self.assertTrue(result["at_threshold_retained"])

    def test_below_60_fails(self):
        self.assertEqual(adjudicate(59.9)["decision"], "FAIL")

    def test_hard_failure_overrides_high_score(self):
        self.assertEqual(adjudicate(95, ["IDENTITY"])["decision"], "FAIL")

    def test_unknown_hard_failure_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported hard failures"):
            adjudicate(90, ["CAMERA_TASTE"])

    def test_multi_actor_long_take_requires_motion_coverage_score(self):
        with self.assertRaisesRegex(ValueError, "visible_actor_motion_score"):
            adjudicate(90, visible_actor_count=4)

    def test_background_freeze_cannot_hide_behind_high_total_score(self):
        result = adjudicate(84, visible_actor_count=4, visible_actor_motion_score=35)
        self.assertEqual(result["decision"], "FAIL")
        self.assertEqual(result["visible_actor_motion_decision"], "FAIL")

    def test_multi_actor_motion_at_60_is_retained(self):
        result = adjudicate(60, visible_actor_count=4, visible_actor_motion_score=60)
        self.assertEqual(result["decision"], "PASS")

    def test_combat_identity_outcome_can_fail_an_otherwise_passing_take(self):
        result = adjudicate(
            82,
            visible_actor_count=4,
            visible_actor_motion_score=75,
            combat_identity_outcome_score=40,
        )
        self.assertEqual(result["combat_identity_outcome_decision"], "FAIL")
        self.assertEqual(result["decision"], "FAIL")

    def test_combat_identity_outcome_hard_failure_overrides_score(self):
        result = adjudicate(
            90,
            ["COMBAT_IDENTITY_OUTCOME"],
            visible_actor_count=4,
            visible_actor_motion_score=90,
            combat_identity_outcome_score=90,
        )
        self.assertEqual(result["decision"], "FAIL")


if __name__ == "__main__":
    unittest.main()
