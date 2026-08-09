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

    def test_fast_model_fails_when_only_normal_or_pro_is_allowed(self):
        config = {"minimum_native_generation_height": 1080, "allowed_generation_models": ["seedance-2.0-pro", "seedance-2.0-normal"], "tasks": [{"task_key": "A", "tool_type": "video_generation", "resolution": "1080p", "model": "seedance-2.0-fast"}]}
        self.assertEqual(evaluate_batch(config)["status"], "FAIL")

    def test_fast_provider_native_720_requires_explicit_delivery_transform(self):
        task = {
            "task_key": "A",
            "tool_type": "video_generation",
            "resolution": "720p",
            "model": "seedance-2.0-fast",
            "provider_native_max_resolution": True,
            "delivery_target_resolution": "1080p",
            "delivery_transform": "DETERMINISTIC_UPSCALE_REQUIRED",
        }
        config = {"minimum_native_generation_height": 1080, "allowed_generation_models": ["seedance-2.0-fast"], "tasks": [task]}
        self.assertEqual(evaluate_batch(config)["status"], "PASS")
