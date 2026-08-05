import unittest

from tools.clean_generated_text_regions import parse_band, parse_ellipse, parse_roi, parse_timed_roi


class CleanGeneratedTextRegionsTests(unittest.TestCase):
    def test_parses_bounded_cleanup_contracts(self):
        self.assertEqual(parse_band("800:1100:1.5:4.0"), (800, 1100, 1.5, 4.0))
        self.assertEqual(parse_roi("10:20:300:80"), (10, 20, 300, 80))
        self.assertEqual(parse_ellipse("100:200:30:40"), (100, 200, 30, 40))
        self.assertEqual(parse_timed_roi("10:20:300:80:1.5:4.0"), (10, 20, 300, 80, 1.5, 4.0))


if __name__ == "__main__":
    unittest.main()
