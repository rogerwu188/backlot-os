import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from release_branding_contract_gate import evaluate


class ReleaseBrandingContractGateTests(unittest.TestCase):
    def _project(self, root: Path) -> dict:
        logo = root / "logo.png"
        chime = root / "chime.wav"
        logo.write_bytes(b"logo")
        chime.write_bytes(b"chime")
        return {
            "releaseProject": True,
            "requireBurnedSubtitles": True,
            "requireBrandedOutro": True,
            "expectedDialogueIds": ["D1", "D2"],
            "metadata": {"episode": "E00"},
            "timeline": {"subtitleTracks": [{
                "enabled": True,
                "clips": [
                    {"dialogue_id": "D1", "text": "A"},
                    {"dialogue_id": "D2", "text": "B"},
                ],
            }]},
            "outro": {
                "enabled": True,
                "brand": "nalu_motion",
                "duration": 3,
                "includeInTotalDuration": True,
                "assetPath": str(logo),
                "audioPath": str(chime),
            },
            "releaseGate": {"required": True},
        }

    def test_complete_project_and_render_pass(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            final = root / "final.mp4"
            final.write_bytes(b"final")
            media_sha = hashlib.sha256(final.read_bytes()).hexdigest()
            render = {
                "coverage": {"subtitles": {"required": True, "count": "2/2"}},
                "outro": {"present": True, "brand": "nalu_motion", "endsAtTimelineEnd": True},
                "releaseGate": {"finalSha256": media_sha},
            }
            result = evaluate(self._project(root), root=root, render_manifest=render, final_video=final)
        self.assertEqual(result["status"], "PASS")

    def test_missing_subtitles_and_outro_fail(self):
        result = evaluate({"metadata": {"episode": "E00"}, "timeline": {"subtitleTracks": []}})
        self.assertIn("release_project_not_declared", result["failures"])
        self.assertIn("burned_subtitles_not_required", result["failures"])
        self.assertIn("outro_not_enabled", result["failures"])

    def test_declared_but_wrong_caption_order_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._project(root)
            project["timeline"]["subtitleTracks"][0]["clips"].reverse()
            result = evaluate(project, root=root)
        self.assertIn("subtitle_order_or_coverage_mismatch", result["failures"])


if __name__ == "__main__":
    unittest.main()
