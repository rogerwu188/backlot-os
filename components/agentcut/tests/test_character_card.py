import copy
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from agentcut import AgentCutEngine, ValidationError
from agentcut.agent import AgentServer
from agentcut.character_card import (
    CharacterCardValidator,
    admit_character_card,
    generate_character_card_prompt,
    seedance_character_binding,
)


def description():
    return {
        "schema": "agentcut.character_description.v1",
        "asset_id": "CHAR-TEST-古装",
        "project_id": "qingshan",
        "character": {
            "id": "CHAR-TEST-古装", "display_name": "测试角色", "stage": "ancient", "seedance_slot": 3,
            "description": {
                "sex_presentation": "male", "age_band": "young adult", "face_shape": "long oval",
                "facial_features": "straight brows, narrow dark eyes, straight nose",
                "hair": "long black hair in a restrained period topknot", "skin_tone": "warm light tan",
                "body_type": "tall lean athletic", "height_proportion": "eight-head proportion",
                "wardrobe": "closed-collar layered gray Song-period robe", "accessories": "plain dark cloth belt only",
                "materials": "matte linen and cotton", "color_palette": "charcoal, ash gray, muted stone",
            },
        },
    }


def manifest(image):
    value = description()
    value["schema"] = "agentcut.character_canonical_card.v1"
    value["card"] = {
        "path": str(image), "aspect_ratio": "16:9",
        "layout": "headshot-left_then-fullbody-front-side-back",
        "views": [
            {"id": "headshot_front", "kind": "headshot", "orientation": "front", "bbox": [0.01, 0.08, 0.22, 0.84]},
            {"id": "fullbody_front", "kind": "fullbody", "orientation": "front", "bbox": [0.26, 0.04, 0.20, 0.92]},
            {"id": "fullbody_side", "kind": "fullbody", "orientation": "side", "bbox": [0.50, 0.04, 0.20, 0.92]},
            {"id": "fullbody_back", "kind": "fullbody", "orientation": "back", "bbox": [0.74, 0.04, 0.20, 0.92]},
        ],
    }
    value["evidence"] = {
        "layout": {"method": "vision-qa", "reviewer": "qa-agent", "recorded_at": "2026-07-19T12:00:00-07:00", "status": "PASS"},
        "identity_consistency": {
            "method": "vision-qa-plus-human", "reviewer": "identity-reviewer",
            "recorded_at": "2026-07-19T12:01:00-07:00", "status": "PASS",
            "checks": {name: True for name in (
                "face_shape", "facial_features", "hair", "skin_tone", "body_type",
                "wardrobe", "accessories", "materials", "color_palette",
            )},
        },
        "full_body_uncropped": {"front": True, "side": True, "back": True},
        "production_constraints": {name: True for name in (
            "neutral_gray_seamless_background", "soft_studio_lighting", "near_orthographic",
            "neutral_pose", "neutral_expression", "no_dynamic_pose", "no_expression_change",
            "single_character_only", "no_redesign",
            "no_complex_background", "no_text", "no_ui", "no_watermark",
        )},
    }
    return value


def registry():
    return {"schema": "ai_drama.continuity_asset_registry.v1", "project_id": "qingshan",
            "assets": {"characters": {}, "scenes": {}, "props": {}}}


class CharacterCardTests(unittest.TestCase):
    @contextmanager
    def probe(self, width=1600, height=900):
        result = Mock(
            returncode=0,
            stdout=json.dumps({"streams": [{"width": width, "height": height, "codec_type": "video"}]}),
            stderr="",
        )
        with patch("agentcut.character_card.shutil.which", return_value="/mock/ffprobe"), \
                patch("agentcut.character_card.subprocess.run", return_value=result):
            yield

    def test_prompt_template_contains_layout_identity_and_forbidden_contract(self):
        result = generate_character_card_prompt(description())
        prompt = result["prompt"]
        self.assertIn("single 16:9", prompt)
        self.assertIn("far-left", prompt)
        self.assertIn("full-body front view", prompt)
        self.assertIn("full-body side view", prompt)
        self.assertIn("full-body back view", prompt)
        self.assertIn("No redesign", prompt)
        self.assertIn("no watermark", prompt)
        self.assertEqual(len(result["promptSha256"]), 64)

    def test_prompt_rejects_missing_structured_identity_field(self):
        value = description()
        del value["character"]["description"]["face_shape"]
        with self.assertRaisesRegex(ValidationError, "face_shape"):
            generate_character_card_prompt(value)

    def test_valid_card_is_admitted_and_emits_seedance_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "card.png"
            image.write_bytes(b"image")
            with self.probe():
                result = CharacterCardValidator("ffprobe").validate(manifest(image))
        self.assertTrue(result["valid"], result["issues"])
        self.assertEqual(result["decision"], "ADMIT")
        self.assertEqual(result["card"]["fullBodyViewCount"], 3)
        self.assertEqual(result["seedanceBinding"]["token"], "[[char_3]]")

    def test_below_three_fullbody_views_hard_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "card.png"
            image.write_bytes(b"image")
            value = manifest(image)
            value["card"]["views"] = value["card"]["views"][:3]
            with self.probe():
                result = CharacterCardValidator("ffprobe").validate(value)
        self.assertFalse(result["valid"])
        self.assertIn("CANONICAL_CARD_FULLBODY_VIEWS_BELOW_3", {x["code"] for x in result["issues"]})

    def test_wrong_layout_order_and_headshot_position_hard_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "card.png"
            image.write_bytes(b"image")
            value = manifest(image)
            value["card"]["views"][0]["bbox"] = [0.30, 0.08, 0.20, 0.84]
            with self.probe():
                result = CharacterCardValidator("ffprobe").validate(value)
        codes = {x["code"] for x in result["issues"]}
        self.assertIn("CANONICAL_CARD_HEADSHOT_NOT_FAR_LEFT", codes)
        self.assertIn("CANONICAL_CARD_LAYOUT_ORDER", codes)

    def test_identity_consistency_evidence_is_not_advisory(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "card.png"
            image.write_bytes(b"image")
            value = manifest(image)
            value["evidence"]["identity_consistency"]["checks"]["hair"] = False
            with self.probe():
                result = CharacterCardValidator("ffprobe").validate(value)
        self.assertFalse(result["valid"])
        self.assertTrue(any(x["path"].endswith("hair") for x in result["issues"]))

    def test_forbidden_content_evidence_is_hard_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "card.png"
            image.write_bytes(b"image")
            value = manifest(image)
            value["evidence"]["production_constraints"]["no_text"] = False
            with self.probe():
                result = CharacterCardValidator("ffprobe").validate(value)
        self.assertFalse(result["valid"])
        self.assertIn("CANONICAL_CARD_PRODUCTION_CONSTRAINT", {x["code"] for x in result["issues"]})

    def test_actual_non_16x9_media_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "card.png"
            image.write_bytes(b"image")
            with self.probe(1024, 1024):
                result = CharacterCardValidator("ffprobe").validate(manifest(image))
        self.assertIn("CANONICAL_CARD_ASPECT_RATIO", {x["code"] for x in result["issues"]})

    def test_invalid_card_cannot_emit_seedance_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "card.png"
            image.write_bytes(b"image")
            value = manifest(image)
            value["evidence"]["full_body_uncropped"]["back"] = False
            with self.probe():
                result = seedance_character_binding(value, ffprobe="ffprobe")
        self.assertFalse(result["bindingAllowed"])
        self.assertIsNone(result["seedanceBinding"])

    def test_registry_dry_run_and_atomic_write_preserve_registry_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "card.png"
            output = Path(directory) / "registry.json"
            image.write_bytes(b"image")
            value = manifest(image)
            with self.probe():
                dry = admit_character_card(value, registry(), ffprobe="ffprobe", dry_run=True)
                written = admit_character_card(value, registry(), ffprobe="ffprobe", dry_run=False, output=output)
            saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(dry["valid"])
        self.assertFalse(dry["written"])
        self.assertTrue(written["written"])
        record = saved["assets"]["characters"]["CHAR-TEST-古装"]
        self.assertEqual(record["status"], "LOCKED_RETURNING")
        self.assertEqual(record["seedance_binding"]["token"], "[[char_3]]")

        mismatched = registry()
        mismatched["project_id"] = "another-project"
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "card.png"
            image.write_bytes(b"image")
            with self.probe(), self.assertRaisesRegex(ValidationError, "project_id"):
                admit_character_card(manifest(image), mismatched, ffprobe="ffprobe", dry_run=True)

    def test_existing_canonical_identity_cannot_be_silently_redesigned(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "card.png"
            image.write_bytes(b"image")
            value = manifest(image)
            with self.probe():
                admitted = admit_character_card(value, registry(), ffprobe="ffprobe", dry_run=True)
                existing = registry()
                existing["assets"]["characters"]["CHAR-TEST-古装"] = admitted["registryRecord"]
                changed = copy.deepcopy(value)
                changed["character"]["description"]["hair"] = "redesigned short hair"
                rejected = admit_character_card(changed, existing, ffprobe="ffprobe", dry_run=True)
        self.assertFalse(rejected["valid"])
        self.assertEqual(rejected["issues"][0]["code"], "CANONICAL_CARD_REDESIGN_REJECTED")

    def test_ndjson_validator_and_binding_use_same_hard_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "card.png"
            image.write_bytes(b"image")
            value = manifest(image)
            server = AgentServer(AgentCutEngine(), workers=1)
            with self.probe():
                validated = server.handle({"id": "v", "method": "validateCharacterCard", "params": {"manifest": value}})
                bound = server.handle({"id": "b", "method": "bindSeedanceCharacter", "params": {"manifest": value}})
        self.assertTrue(validated["result"]["valid"])
        self.assertEqual(bound["result"]["binding"]["token"], "[[char_3]]")


if __name__ == "__main__":
    unittest.main()
