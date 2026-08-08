import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.asset_binding_validator import build_errors


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WardrobeVariantRegistrationGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.identity = root / "identity.png"
        self.identity.write_bytes(b"identity-parent")
        self.wardrobe = root / "wardrobe.png"
        self.wardrobe.write_bytes(b"wardrobe-variant")
        self.registry_path = root / "registry.json"
        self.registry = {"assets": {"characters": {"CHAR-A": {
            "status": "LOCKED_RETURNING",
            "identity_reference_image": str(self.identity),
            "identity_lock": {"face": "locked"},
            "wardrobe_variants": {"white_v1": {
                "reference_image": str(self.wardrobe),
                "reference_sha256": sha256(self.wardrobe),
                "allowed_context": "test",
                "identity_verification": "PASS",
                "verification_status": "PASS",
            }},
        }}}}
        self.registry_path.write_text(json.dumps(self.registry), encoding="utf-8")
        self.config = {"character_state": {"CHAR-A": {
            "wardrobe_variant_id": "white_v1",
            "wardrobe_reference_image": str(self.wardrobe),
        }}, "shots": []}
        self.manifest = {
            "historical_asset_inheritance_required": True,
            "series_character_registry": str(self.registry_path),
            "characters": {"CHAR-A": {
                "history_status": "RETURNING",
                "identity_reference_image": str(self.identity),
                "reference_image": str(self.wardrobe),
                "wardrobe_variant_id": "white_v1",
                "wardrobe_variant_required": True,
                "level": "B",
            }},
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_registered_identity_verified_exact_sha_variant_passes(self):
        self.assertEqual(build_errors(self.config, self.manifest), [])

    def test_required_but_missing_variant_id_fails_closed(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["characters"]["CHAR-A"].pop("wardrobe_variant_id")
        self.assertTrue(any("requires registered wardrobe variant" in error for error in build_errors(self.config, manifest)))

    def test_unregistered_variant_fails_closed(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["characters"]["CHAR-A"]["wardrobe_variant_id"] = "missing"
        self.assertTrue(any("wardrobe variant is not registered" in error for error in build_errors(self.config, manifest)))

    def test_identity_qa_must_pass(self):
        registry = copy.deepcopy(self.registry)
        registry["assets"]["characters"]["CHAR-A"]["wardrobe_variants"]["white_v1"]["identity_verification"] = "PENDING"
        self.registry_path.write_text(json.dumps(registry), encoding="utf-8")
        self.assertTrue(any("lacks same-face/same-body PASS" in error for error in build_errors(self.config, self.manifest)))

    def test_declared_variant_sha_must_match_disk(self):
        registry = copy.deepcopy(self.registry)
        registry["assets"]["characters"]["CHAR-A"]["wardrobe_variants"]["white_v1"]["reference_sha256"] = "0" * 64
        self.registry_path.write_text(json.dumps(registry), encoding="utf-8")
        self.assertTrue(any("wardrobe variant CHAR-A/white_v1 SHA mismatch" in error for error in build_errors(self.config, self.manifest)))

    def test_state_bible_and_production_binding_must_match(self):
        config = copy.deepcopy(self.config)
        config["character_state"]["CHAR-A"]["wardrobe_variant_id"] = "other"
        self.assertTrue(any("State Bible wardrobe variant does not match" in error for error in build_errors(config, self.manifest)))


if __name__ == "__main__":
    unittest.main()
