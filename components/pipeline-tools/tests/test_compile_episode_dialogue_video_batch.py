import tempfile
import unittest
from pathlib import Path

from tools.compile_episode_dialogue_video_batch import compile_batch


class CompileEpisodeDialogueVideoBatchTests(unittest.TestCase):
    def test_compiles_all_lines_in_one_batch(self):
        script = {"episode": "E99", "dialogue_draft": [
            {"dia_id": "DIA-001", "speaker": "陈迹", "text": "一。", "beat_id": "B01"},
            {"dia_id": "DIA-002", "speaker": "张夏", "text": "二。", "beat_id": "B01"},
        ]}
        images = {"tasks": [{"task_key": "E99-B01-IMAGE", "state": "image_pass", "output_path": "/tmp/B01.png"}]}
        scene_state = {"_source_path": "scene.json", "scene_state": [{"scene_id": "S1", "time_of_day": "dusk", "weather": "clear", "location": "account room"}]}
        with tempfile.TemporaryDirectory() as tmp:
            result = compile_batch(script, images, scene_state, Path(tmp))
        self.assertEqual(2, len(result["tasks"]))
        self.assertEqual("E99-DIA-001-VIDEO", result["tasks"][0]["task_key"])


if __name__ == "__main__":
    unittest.main()
