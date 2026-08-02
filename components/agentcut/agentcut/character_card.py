from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .errors import AgentCutError, ValidationError
from .transform import content_hash, write_json_atomic


CAPABILITY_ID = "CL2X-358"
CAPABILITY_VERSION = "1.0"
DESCRIPTION_SCHEMA = "agentcut.character_description.v1"
MANIFEST_SCHEMA = "agentcut.character_canonical_card.v1"
REGISTRY_SCHEMA = "ai_drama.continuity_asset_registry.v1"
LAYOUT = "headshot-left_then-fullbody-front-side-back"

DESCRIPTION_FIELDS = (
    "sex_presentation", "age_band", "face_shape", "facial_features", "hair",
    "skin_tone", "body_type", "height_proportion", "wardrobe", "accessories",
    "materials", "color_palette",
)
IDENTITY_CHECKS = (
    "face_shape", "facial_features", "hair", "skin_tone", "body_type",
    "wardrobe", "accessories", "materials", "color_palette",
)
PRODUCTION_CONSTRAINTS = (
    "neutral_gray_seamless_background", "soft_studio_lighting", "near_orthographic",
    "neutral_pose", "neutral_expression", "no_dynamic_pose", "no_expression_change",
    "single_character_only", "no_redesign",
    "no_complex_background", "no_text", "no_ui", "no_watermark",
)
REQUIRED_VIEWS = (
    ("headshot_front", "headshot", "front"),
    ("fullbody_front", "fullbody", "front"),
    ("fullbody_side", "fullbody", "side"),
    ("fullbody_back", "fullbody", "back"),
)


def _load_object(source: str | Path | dict[str, Any]) -> tuple[dict[str, Any], Path | None]:
    if isinstance(source, dict):
        return copy.deepcopy(source), None
    path = Path(source).expanduser().resolve()
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must contain a JSON object")
    return value, path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{path} must be a non-empty string")
    return value.strip()


def _character_parts(source: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    schema = source.get("schema")
    if schema not in {DESCRIPTION_SCHEMA, MANIFEST_SCHEMA}:
        raise ValidationError(f"schema must be {DESCRIPTION_SCHEMA!r} or {MANIFEST_SCHEMA!r}")
    asset_id = _required_string(source.get("asset_id"), "asset_id")
    _required_string(source.get("project_id"), "project_id")
    character = source.get("character")
    if not isinstance(character, dict):
        raise ValidationError("character must be an object")
    character_id = _required_string(character.get("id"), "character.id")
    if character_id != asset_id:
        raise ValidationError("character.id must equal asset_id")
    _required_string(character.get("display_name"), "character.display_name")
    _required_string(character.get("stage"), "character.stage")
    slot = character.get("seedance_slot")
    if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 99:
        raise ValidationError("character.seedance_slot must be an integer from 1 through 99")
    description = character.get("description")
    if not isinstance(description, dict):
        raise ValidationError("character.description must be an object")
    for field in DESCRIPTION_FIELDS:
        _required_string(description.get(field), f"character.description.{field}")
    return asset_id, character_id, character


def generate_character_card_prompt(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    value, _ = _load_object(source)
    asset_id, _character_id, character = _character_parts(value)
    description = character["description"]
    template_path = Path(__file__).resolve().parent / "templates" / "canonical-character-card-v1.txt"
    if not template_path.is_file():
        raise AgentCutError(f"canonical character-card prompt template is missing: {template_path}")
    prompt = template_path.read_text(encoding="utf-8").format(
        display_name=character["display_name"], asset_id=asset_id, stage=character["stage"],
        **{field: description[field] for field in DESCRIPTION_FIELDS},
    ).strip()
    return {
        "capability": CAPABILITY_ID, "capabilityVersion": CAPABILITY_VERSION,
        "template": "canonical-character-card-v1", "assetId": asset_id,
        "prompt": prompt, "promptSha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "expectedManifestSchema": MANIFEST_SCHEMA,
    }


def _issue(issues: list[dict[str, Any]], code: str, path: str, message: str) -> None:
    issues.append({"code": code, "severity": "error", "path": path, "message": message})


def _bbox(value: Any, path: str, issues: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    if not isinstance(value, list) or len(value) != 4 or any(
        isinstance(item, bool) or not isinstance(item, (int, float)) for item in value
    ):
        _issue(issues, "CANONICAL_CARD_BBOX_INVALID", path, "bbox must be [x,y,width,height] numbers")
        return None
    x, y, width, height = (float(item) for item in value)
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1.000001 or y + height > 1.000001:
        _issue(issues, "CANONICAL_CARD_BBOX_OUT_OF_BOUNDS", path, "bbox must fit normalized image bounds")
        return None
    return x, y, width, height


def _probe_image(ffprobe: str, path: Path) -> tuple[int | None, int | None, str | None]:
    if shutil.which(ffprobe) is None and not Path(ffprobe).is_file():
        return None, None, "FFprobe is unavailable"
    proc = subprocess.run([
        ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height,codec_type", "-of", "json", str(path),
    ], capture_output=True, text=True)
    if proc.returncode != 0:
        return None, None, proc.stderr.strip() or "FFprobe failed"
    try:
        stream = json.loads(proc.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"]), None
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None, None, "image dimensions are unavailable"


class CharacterCardValidator:
    def __init__(self, ffprobe: str) -> None:
        self.ffprobe = ffprobe

    def validate(self, source: str | Path | dict[str, Any]) -> dict[str, Any]:
        manifest, manifest_path = _load_object(source)
        issues: list[dict[str, Any]] = []
        try:
            asset_id, _character_id, character = _character_parts(manifest)
        except ValidationError as exc:
            _issue(issues, "CANONICAL_CARD_FIELD_REQUIRED", "manifest", str(exc))
            asset_id = str(manifest.get("asset_id") or "")
            character = manifest.get("character") if isinstance(manifest.get("character"), dict) else {}

        card = manifest.get("card")
        if not isinstance(card, dict):
            _issue(issues, "CANONICAL_CARD_SECTION_REQUIRED", "card", "card must be an object")
            card = {}
        card_path_value = card.get("path")
        image_path: Path | None = None
        width = height = None
        image_sha = None
        if not isinstance(card_path_value, str) or not card_path_value.strip():
            _issue(issues, "CANONICAL_CARD_IMAGE_REQUIRED", "card.path", "card.path must be a non-empty path")
        else:
            image_path = Path(card_path_value).expanduser()
            if not image_path.is_absolute() and manifest_path is not None:
                image_path = manifest_path.parent / image_path
            image_path = image_path.resolve()
            if not image_path.is_file() or image_path.stat().st_size == 0:
                _issue(issues, "CANONICAL_CARD_IMAGE_MISSING", "card.path", f"image is missing or empty: {image_path}")
            else:
                if image_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    _issue(issues, "CANONICAL_CARD_NOT_STILL_IMAGE", "card.path", "card must be one PNG, JPEG, or WebP still image")
                image_sha = _sha256(image_path)
                width, height, probe_error = _probe_image(self.ffprobe, image_path)
                if probe_error:
                    _issue(issues, "CANONICAL_CARD_IMAGE_PROBE_FAILED", "card.path", probe_error)
                elif height == 0 or width is None or height is None or abs(width / height - 16 / 9) > 0.01:
                    _issue(issues, "CANONICAL_CARD_ASPECT_RATIO", "card.path", f"actual image must be 16:9, got {width}x{height}")
        if card.get("aspect_ratio") != "16:9":
            _issue(issues, "CANONICAL_CARD_ASPECT_DECLARATION", "card.aspect_ratio", "aspect_ratio must be 16:9")
        if card.get("layout") != LAYOUT:
            _issue(issues, "CANONICAL_CARD_LAYOUT", "card.layout", f"layout must be {LAYOUT}")

        views = card.get("views")
        view_map: dict[str, tuple[dict[str, Any], tuple[float, float, float, float] | None]] = {}
        if not isinstance(views, list):
            _issue(issues, "CANONICAL_CARD_VIEWS_REQUIRED", "card.views", "views must be an array")
            views = []
        for index, view in enumerate(views):
            if not isinstance(view, dict):
                _issue(issues, "CANONICAL_CARD_VIEW_INVALID", f"card.views[{index}]", "view must be an object")
                continue
            view_id = view.get("id")
            if not isinstance(view_id, str) or not view_id:
                _issue(issues, "CANONICAL_CARD_VIEW_ID_REQUIRED", f"card.views[{index}].id", "view id is required")
                continue
            if view_id in view_map:
                _issue(issues, "CANONICAL_CARD_VIEW_DUPLICATE", f"card.views[{index}].id", f"duplicate view id: {view_id}")
                continue
            view_map[view_id] = (view, _bbox(view.get("bbox"), f"card.views[{index}].bbox", issues))
        fullbody_count = sum(1 for view, _box in view_map.values() if view.get("kind") == "fullbody")
        if fullbody_count < 3:
            _issue(issues, "CANONICAL_CARD_FULLBODY_VIEWS_BELOW_3", "card.views", "at least three full-body views are required")
        for view_id, kind, orientation in REQUIRED_VIEWS:
            row = view_map.get(view_id)
            if row is None:
                _issue(issues, "CANONICAL_CARD_REQUIRED_VIEW_MISSING", "card.views", f"missing {view_id}")
                continue
            view, _box = row
            if view.get("kind") != kind or view.get("orientation") != orientation:
                _issue(issues, "CANONICAL_CARD_VIEW_ROLE_MISMATCH", f"card.views.{view_id}", f"expected {kind}/{orientation}")
        ordered_boxes = [view_map.get(view_id, ({}, None))[1] for view_id, _kind, _orientation in REQUIRED_VIEWS]
        if all(box is not None for box in ordered_boxes):
            boxes = [box for box in ordered_boxes if box is not None]
            if boxes[0][0] > 0.05:
                _issue(issues, "CANONICAL_CARD_HEADSHOT_NOT_FAR_LEFT", "card.views.headshot_front.bbox", "headshot must begin at the far-left edge")
            if any(left[0] + left[2] > right[0] + 1e-6 for left, right in zip(boxes, boxes[1:])):
                _issue(issues, "CANONICAL_CARD_LAYOUT_ORDER", "card.views", "views must be non-overlapping left-to-right: headshot, front, side, back")

        evidence = manifest.get("evidence")
        if not isinstance(evidence, dict):
            _issue(issues, "CANONICAL_CARD_EVIDENCE_REQUIRED", "evidence", "evidence must be an object")
            evidence = {}
        for section_name in ("layout", "identity_consistency"):
            section = evidence.get(section_name)
            if not isinstance(section, dict):
                _issue(issues, "CANONICAL_CARD_EVIDENCE_SECTION_REQUIRED", f"evidence.{section_name}", "evidence section is required")
                continue
            for field in ("method", "reviewer", "recorded_at"):
                if not isinstance(section.get(field), str) or not section[field].strip():
                    _issue(issues, "CANONICAL_CARD_EVIDENCE_PROVENANCE", f"evidence.{section_name}.{field}", f"{field} is required")
            if section.get("status") != "PASS":
                _issue(issues, "CANONICAL_CARD_EVIDENCE_NOT_PASS", f"evidence.{section_name}.status", "status must be PASS")
        identity_section = evidence.get("identity_consistency") if isinstance(evidence.get("identity_consistency"), dict) else {}
        checks = identity_section.get("checks") if isinstance(identity_section.get("checks"), dict) else {}
        for name in IDENTITY_CHECKS:
            if checks.get(name) is not True:
                _issue(issues, "CANONICAL_CARD_IDENTITY_INCONSISTENT", f"evidence.identity_consistency.checks.{name}", "identity consistency check must be true")
        uncropped = evidence.get("full_body_uncropped") if isinstance(evidence.get("full_body_uncropped"), dict) else {}
        for orientation in ("front", "side", "back"):
            if uncropped.get(orientation) is not True:
                _issue(issues, "CANONICAL_CARD_FULLBODY_CROPPED", f"evidence.full_body_uncropped.{orientation}", "full body must be uncropped")
        constraints = evidence.get("production_constraints") if isinstance(evidence.get("production_constraints"), dict) else {}
        for name in PRODUCTION_CONSTRAINTS:
            if constraints.get(name) is not True:
                _issue(issues, "CANONICAL_CARD_PRODUCTION_CONSTRAINT", f"evidence.production_constraints.{name}", "constraint must be explicitly true")

        valid = not issues
        slot = character.get("seedance_slot") if isinstance(character, dict) else None
        binding = None
        if valid:
            binding = {
                "token": f"[[char_{slot}]]", "slot": slot, "assetId": asset_id,
                "canonicalCard": str(image_path), "canonicalCardSha256": image_sha,
            }
        return {
            "capability": CAPABILITY_ID, "capabilityVersion": CAPABILITY_VERSION,
            "valid": valid, "decision": "ADMIT" if valid else "REJECT_ASSET",
            "assetId": asset_id or None, "manifestHash": content_hash(manifest),
            "card": {"path": str(image_path) if image_path else None, "sha256": image_sha,
                     "width": width, "height": height, "fullBodyViewCount": fullbody_count},
            "seedanceBinding": binding, "issues": issues,
        }


def seedance_character_binding(source: str | Path | dict[str, Any], *, ffprobe: str) -> dict[str, Any]:
    report = CharacterCardValidator(ffprobe).validate(source)
    if not report["valid"]:
        return {**report, "bindingAllowed": False}
    return {**report, "bindingAllowed": True, "binding": report["seedanceBinding"]}


def admit_character_card(
    source: str | Path | dict[str, Any], registry: str | Path | dict[str, Any], *,
    ffprobe: str, dry_run: bool = True, output: str | Path | None = None,
) -> dict[str, Any]:
    manifest, _manifest_path = _load_object(source)
    report = CharacterCardValidator(ffprobe).validate(source)
    if not report["valid"]:
        return {**report, "dryRun": dry_run, "written": False, "registryChanged": False}
    registry_value, registry_path = _load_object(registry)
    if registry_value.get("schema") != REGISTRY_SCHEMA:
        raise ValidationError(f"registry.schema must be {REGISTRY_SCHEMA}")
    project_id = _required_string(registry_value.get("project_id"), "registry.project_id")
    manifest_project_id = _required_string(manifest.get("project_id"), "manifest.project_id")
    if manifest_project_id != project_id:
        raise ValidationError("manifest.project_id must equal registry.project_id")
    assets = registry_value.get("assets")
    if not isinstance(assets, dict):
        raise ValidationError("registry.assets must be an object")
    for kind in ("characters", "scenes", "props"):
        if not isinstance(assets.get(kind), dict):
            raise ValidationError(f"registry.assets.{kind} must be an object")
    asset_id = report["assetId"]
    existing = assets["characters"].get(asset_id)
    existing_hash = existing.get("agentcut_canonical_card", {}).get("manifest_sha256") if isinstance(existing, dict) else None
    if existing is not None and existing_hash != report["manifestHash"]:
        return {
            **report, "valid": False, "decision": "REJECT_ASSET", "dryRun": dry_run,
            "written": False, "registryChanged": False,
            "issues": [{"code": "CANONICAL_CARD_REDESIGN_REJECTED", "severity": "error",
                        "path": f"assets.characters.{asset_id}",
                        "message": "an admitted canonical identity cannot be silently replaced"}],
        }
    character = manifest["character"]
    stage = character["stage"]
    record = {
        "status": "LOCKED_RETURNING",
        "identity_lock": copy.deepcopy(character["description"]),
        "canonical_reference_image": report["card"]["path"],
        "canonical_source": MANIFEST_SCHEMA,
        "variants": {
            stage: {
                "reference_image": report["card"]["path"], "source": report["manifestHash"],
                "allowed_context": "canonical identity anchor", "verification_status": "PASS",
            }
        },
        "agentcut_canonical_card": {
            "capability": CAPABILITY_ID, "version": CAPABILITY_VERSION,
            "manifest_sha256": report["manifestHash"], "image_sha256": report["card"]["sha256"],
            "layout": LAYOUT, "full_body_views": 3,
        },
        "seedance_binding": report["seedanceBinding"],
    }
    changed = existing != record
    next_registry = copy.deepcopy(registry_value)
    next_registry["assets"]["characters"][asset_id] = record
    written = False
    destination = None
    if not dry_run and changed:
        if output is None:
            raise ValidationError("output is required unless dryRun is true")
        destination = write_json_atomic(output, next_registry)
        written = True
    elif not dry_run:
        destination = str(Path(output).resolve()) if output else (str(registry_path) if registry_path else None)
    return {
        **report, "projectId": project_id, "dryRun": dry_run, "written": written,
        "registryChanged": changed, "output": destination,
        "registryBeforeHash": content_hash(registry_value),
        "registryAfterHash": content_hash(next_registry),
        "registryRecord": record,
    }
