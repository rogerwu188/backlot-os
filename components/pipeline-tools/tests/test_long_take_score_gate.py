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


if __name__ == "__main__":
    unittest.main()
