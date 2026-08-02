import unittest

from tools.repair_periodic_duplicate_frames import audio_filter, consecutive_ranges, select_expression


class DuplicateFrameRepairTest(unittest.TestCase):
    def test_expression_deletes_only_listed_frames(self):
        self.assertEqual(select_expression([3, 7, 11]), "not(eq(n\\,3)+eq(n\\,7)+eq(n\\,11))")

    def test_consecutive_ranges_group_only_adjacent_frames(self):
        self.assertEqual(consecutive_ranges([7, 3, 4, 11]), [(3, 4), (7, 7), (11, 11)])

    def test_audio_filter_removes_matching_frame_intervals(self):
        value = audio_filter([3, 4], 24.0, 1.0)
        self.assertIn("atrim=start=0.000000000:end=0.125000000", value)
        self.assertIn("atrim=start=0.208333333:end=1.000000000", value)
        self.assertIn("concat=n=2:v=0:a=1[aout]", value)


if __name__ == "__main__":
    unittest.main()
