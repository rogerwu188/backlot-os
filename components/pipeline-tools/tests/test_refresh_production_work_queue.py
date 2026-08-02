import unittest

from tools.refresh_production_work_queue import episode_process_map, is_release_active_status


class ReleaseActivityTests(unittest.TestCase):
    def test_platform_review_is_real_release_activity(self):
        self.assertTrue(is_release_active_status("DOUYIN_PLATFORM_REVIEW_PENDING"))
        self.assertTrue(is_release_active_status("PLATFORM_REVIEWING"))

    def test_completed_local_batch_is_not_release_activity(self):
        self.assertFalse(is_release_active_status("BATCH_COMPLETE"))

    def test_agentcut_render_batch_maps_one_pid_to_each_episode(self):
        processes = episode_process_map(
            " 34306 agentcut render-batch configs/e26_agentcut_v6.json configs/e27_agentcut_v7.json\n"
            " 33690 python tools/episode_parallel_batch_supervisor.py --config configs/E28_video.json\n"
            " 33701 .ai_review_env/bin/qingshan-review review-many qa/e29_video_review.json\n"
            " 99999 python tools/refresh_production_work_queue.py\n"
        )
        self.assertEqual(processes, {"E26": [34306], "E27": [34306], "E28": [33690], "E29": [33701]})


if __name__ == "__main__":
    unittest.main()
