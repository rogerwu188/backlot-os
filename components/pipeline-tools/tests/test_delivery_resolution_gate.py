import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_resolution_gate import evaluate_batch


class DeliveryResolutionGateTests(unittest.TestCase):
    def test_native_1080_passes(self):
        config = {"minimum_native_generation_height": 1080, "tasks": [{"task_key": "A", "tool_type": "video_generation", "resolution": "1080p"}]}
        self.assertEqual(evaluate_batch(config)["status"], "PASS")

    def test_720_upscale_fails(self):
        config = {"minimum_native_generation_height": 1080, "tasks": [{"task_key": "A", "tool_type": "video_generation", "resolution": "720p", "resolution_source": "UPSCALED_FROM_LOWER_RESOLUTION"}]}
        self.assertEqual(evaluate_batch(config)["status"], "FAIL")
