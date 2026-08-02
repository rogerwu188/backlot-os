from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .longtake import LongTakeValidator


CAPABILITY_ID = "CL2X-353"
CAPABILITY_VERSION = "1.0"
GENERATION_MODE = "image_to_video_first_last"
ENDPOINT = "/api/v1/generation/image-to-video"
ROLES = ("start_frame", "end_frame")
MODELS = {"seedance-2.0-pro", "seedance-2.0-fast"}
ASPECT_RATIOS = {"16:9", "9:16", "4:3", "1:1", "3:4", "21:9", "adaptive"}
RESOLUTIONS = {"720p", "480p"}


def _load_object(source: str | Path | dict[str, Any]) -> tuple[dict[str, Any], Path]:
    if isinstance(source, dict):
        return json.loads(json.dumps(source)), Path.cwd()
    path = Path(source).resolve()
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValidationError("first/last generation task must be a JSON object")
    return value, path.parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_media(value: Any, base: Path, location: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{location}.source must be a non-empty local path")
    path = Path(value).expanduser()
    path = path if path.is_absolute() else base / path
    path = path.resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise ValidationError(f"{location}.source is missing or empty: {path}")
    return path


def _field(task: dict[str, Any], snake: str, camel: str, default: Any = None) -> Any:
    if snake in task and camel in task and task[snake] != task[camel]:
        raise ValidationError(f"conflicting {snake} and {camel} values")
    return task[snake] if snake in task else task.get(camel, default)


def prepare_first_last_submission(
    source: str | Path | dict[str, Any], *, client: str = "tools/giggle_api_client.py",
    include_command: bool = False,
) -> dict[str, Any]:
    """Compile a paid-submission-safe Giggle first/last-frame task.

    This function never performs the remote request.  It validates the role
    contract and emits the only permitted endpoint/subcommand for the caller.
    """
    task, base = _load_object(source)
    if task.get("version", "1.0") != "1.0":
        raise ValidationError("first/last generation task version must be '1.0'")
    generation_mode = _field(task, "generation_mode", "generationMode")
    if generation_mode != GENERATION_MODE:
        raise ValidationError(f"generation_mode must be {GENERATION_MODE!r}")
    forbidden = [name for name in ("referenceImages", "reference_images", "images", "anchors") if task.get(name)]
    if forbidden:
        raise ValidationError(
            "first/last mode forbids generic image inputs; do not fall back to images[]: " + ", ".join(forbidden)
        )
    task_key = _field(task, "task_key", "taskKey")
    if not isinstance(task_key, str) or not task_key.strip():
        raise ValidationError("task_key must be a non-empty string")
    inputs = task.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 2:
        raise ValidationError("inputs must contain exactly one start_frame and one end_frame")
    by_role: dict[str, Path] = {}
    for index, item in enumerate(inputs):
        if not isinstance(item, dict):
            raise ValidationError(f"inputs[{index}] must be an object")
        role = item.get("role")
        if role not in ROLES:
            raise ValidationError(f"inputs[{index}].role must be start_frame or end_frame")
        if role in by_role:
            raise ValidationError(f"inputs contains duplicate role: {role}")
        by_role[role] = _resolve_media(item.get("source"), base, f"inputs[{index}]")
    missing = [role for role in ROLES if role not in by_role]
    if missing:
        raise ValidationError("inputs is missing required role(s): " + ", ".join(missing))

    prompt = task.get("prompt")
    prompt_file = _field(task, "prompt_file", "promptFile")
    if bool(prompt) == bool(prompt_file):
        raise ValidationError("provide exactly one of prompt or promptFile")
    if prompt_file:
        prompt_path = Path(str(prompt_file)).expanduser()
        prompt_path = prompt_path if prompt_path.is_absolute() else base / prompt_path
        if not prompt_path.is_file():
            raise ValidationError(f"promptFile does not exist: {prompt_path.resolve()}")
        prompt = prompt_path.read_text(encoding="utf-8")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValidationError("prompt must be non-empty")
    if len(prompt) > 10_000:
        raise ValidationError("prompt exceeds the Giggle 10,000-character limit")

    model = task.get("model", "seedance-2.0-pro")
    duration = task.get("duration", 15)
    aspect_ratio = _field(task, "aspect_ratio", "aspectRatio", "9:16")
    resolution = task.get("resolution", "720p")
    count = _field(task, "generating_count", "generatingCount", 1)
    if model not in MODELS:
        raise ValidationError("model must be seedance-2.0-pro or seedance-2.0-fast")
    if isinstance(duration, bool) or not isinstance(duration, int) or not 4 <= duration <= 15:
        raise ValidationError("duration must be an integer from 4 through 15")
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValidationError("aspectRatio is not supported by Giggle image-to-video")
    if resolution not in RESOLUTIONS:
        raise ValidationError("resolution must be 720p or 480p")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 4:
        raise ValidationError("generatingCount must be an integer from 1 through 4")

    roles = {
        role: {"source": str(path), "sha256": _sha256(path), "size": path.stat().st_size}
        for role, path in by_role.items()
    }
    argv = [
        sys.executable, client, "image-to-video", "--prompt", prompt,
        "--start-frame", str(by_role["start_frame"]),
        "--end-frame", str(by_role["end_frame"]),
        "--model", model, "--duration", str(duration),
        "--aspect-ratio", aspect_ratio, "--resolution", resolution,
        "--count", str(count),
    ]
    result: dict[str, Any] = {
        "capability": CAPABILITY_ID,
        "capabilityVersion": CAPABILITY_VERSION,
        "allowed": True,
        "decision": "ALLOW_PAID_SUBMISSION",
        "taskKey": task_key,
        "generationMode": GENERATION_MODE,
        "generation_mode": GENERATION_MODE,
        "request": {
            "method": "POST",
            "endpoint": ENDPOINT,
            "model": model,
            "duration": duration,
            "aspectRatio": aspect_ratio,
            "resolution": resolution,
            "generatingCount": count,
            "promptSha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        },
        "inputRoles": roles,
        "routing": {
            "clientSubcommand": "image-to-video",
            "forbiddenEndpoint": "/api/v1/generation/omni-video",
            "forbiddenPayloadField": "images",
            "silentFallbackAllowed": False,
        },
        "postGenerationGate": {"method": "finalizeFirstLastGeneration", "hardCutAuditRequired": True},
    }
    if include_command:
        result["argv"] = argv
    return result


def finalize_first_last_submission(
    source: str | Path | dict[str, Any], video: str | Path, task_id: str, *,
    ffmpeg: str, ffprobe: str, scene_threshold: float = 0.20,
) -> dict[str, Any]:
    """Produce an endpoint/role/SHA receipt and enforce the hard-cut gate."""
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValidationError("taskId must be a non-empty string")
    prepared = prepare_first_last_submission(source)
    audit = LongTakeValidator(ffmpeg, ffprobe).validate(
        video, scene_threshold=scene_threshold, continuous_camera_required=True,
    )
    return {
        "capability": CAPABILITY_ID,
        "capabilityVersion": CAPABILITY_VERSION,
        "accepted": audit["valid"],
        "decision": "ACCEPT_FOR_DOWNSTREAM_QA" if audit["valid"] else "REJECT_HARD_CUT",
        "taskKey": prepared["taskKey"],
        "taskId": task_id,
        "generationMode": GENERATION_MODE,
        "endpoint": ENDPOINT,
        "inputRoles": prepared["inputRoles"],
        "video": {"path": audit["video"], "sha256": audit["sha256"], "duration": audit["duration"]},
        "continuityAudit": audit,
        "remainingQAGates": ["cadence", "OCR", "ASR"],
    }
