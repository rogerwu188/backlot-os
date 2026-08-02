"""Structural validation of a project-intake payload.

Default path is stdlib-only (hand-rolled checks against the shape of
contracts/project-intake.schema.json) because the sandbox this package was
built in does not have the ``jsonschema`` PyPI package installed. If
``jsonschema`` IS importable at runtime, it is used for a stricter check;
otherwise the hand-rolled validator runs. Both paths return the same
structured-error shape: a list of {"field", "reason"} dicts, never a raw
traceback.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

PRODUCTION_TYPES = {"short_drama", "long_drama"}
VISUAL_FORMATS = {"live_action", "animation"}
ASPECT_RATIOS = {"9:16", "16:9"}
REQUIRED_FIELDS = ("source", "production_type", "visual_format", "episode_count", "episode_duration_seconds", "aspect_ratio")


def _try_jsonschema(payload: dict) -> list[dict] | None:
    try:
        import jsonschema  # type: ignore
        import json
        from pathlib import Path
    except ImportError:
        return None
    schema_path = Path(__file__).resolve().parent / "schemas" / "project-intake.schema.json"
    if not schema_path.is_file():
        return None
    try:
        with schema_path.open(encoding="utf-8") as stream:
            schema = json.load(stream)
        validator_cls = jsonschema.validators.validator_for(schema)
        validator = validator_cls(schema, format_checker=jsonschema.FormatChecker())
        errors = []
        for error in validator.iter_errors(payload):
            field = "/".join(str(part) for part in error.path) or "<root>"
            errors.append({"field": field, "reason": error.message})
        return errors
    except Exception:
        # Any jsonschema incompatibility (older/newer API) falls back to the
        # hand-rolled validator rather than raising -- never a raw traceback.
        return None


def _hand_rolled(payload: dict) -> list[dict]:
    errors: list[dict] = []
    if not isinstance(payload, dict):
        return [{"field": "<root>", "reason": "payload must be a JSON object"}]
    for field in REQUIRED_FIELDS:
        if field not in payload:
            errors.append({"field": field, "reason": "required field is missing"})
    source = payload.get("source")
    if source is not None:
        if not isinstance(source, dict):
            errors.append({"field": "source", "reason": "source must be an object with a string 'url' or 'upload'"})
        else:
            selected = [key for key in ("url", "upload") if isinstance(source.get(key), str) and source.get(key).strip()]
            if len(selected) != 1:
                errors.append({"field": "source", "reason": "source must contain exactly one non-empty 'url' or 'upload'"})
            elif selected[0] == "url":
                parsed = urlsplit(source["url"])
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    errors.append({"field": "source/url", "reason": "must be an absolute http or https URL"})
            extra_source = set(source) - {"url", "upload"}
            for key in sorted(extra_source):
                errors.append({"field": f"source/{key}", "reason": "unexpected field"})
    if "production_type" in payload and payload["production_type"] not in PRODUCTION_TYPES:
        errors.append({"field": "production_type", "reason": f"must be one of {sorted(PRODUCTION_TYPES)}"})
    if "visual_format" in payload and payload["visual_format"] not in VISUAL_FORMATS:
        errors.append({"field": "visual_format", "reason": f"must be one of {sorted(VISUAL_FORMATS)}"})
    if "aspect_ratio" in payload and payload["aspect_ratio"] not in ASPECT_RATIOS:
        errors.append({"field": "aspect_ratio", "reason": f"must be one of {sorted(ASPECT_RATIOS)}"})
    episode_count = payload.get("episode_count")
    if "episode_count" in payload and (not isinstance(episode_count, int) or isinstance(episode_count, bool) or not (1 <= episode_count <= 1000)):
        errors.append({"field": "episode_count", "reason": "must be an integer between 1 and 1000"})
    duration = payload.get("episode_duration_seconds")
    if "episode_duration_seconds" in payload and (not isinstance(duration, int) or isinstance(duration, bool) or not (30 <= duration <= 7200)):
        errors.append({"field": "episode_duration_seconds", "reason": "must be an integer between 30 and 7200"})
    extra_keys = set(payload.keys()) - set(REQUIRED_FIELDS)
    for key in extra_keys:
        errors.append({"field": key, "reason": "unexpected field (additionalProperties is false)"})
    return errors


def validate_intake(payload: dict) -> dict:
    """Return {"ok": bool, "errors": [...], "engine": "jsonschema"|"hand_rolled"}."""
    schema_errors = _try_jsonschema(payload)
    semantic_errors = _hand_rolled(payload)
    engine = "jsonschema+semantic" if schema_errors is not None else "hand_rolled"
    errors = semantic_errors if schema_errors is None else schema_errors + semantic_errors
    deduped = []
    seen = set()
    for error in errors:
        identity = (error.get("field"), error.get("reason"))
        if identity not in seen:
            seen.add(identity)
            deduped.append(error)
    errors = deduped
    return {"ok": not errors, "errors": errors, "engine": engine}
