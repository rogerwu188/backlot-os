#!/usr/bin/env python3
"""Fail-closed transport policy for exact-first-frame video tasks.

An image labelled ``EXACT_FIRST_FRAME`` is not an ordinary multimodal
reference.  It must travel through the provider's native image-to-video
``start_frame`` field and must carry explicit pre-encode and post-harvest
authority contracts.  This module deliberately does not repair media.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from PIL import Image


EXACT_FIRST_FRAME_ROLE = "EXACT_FIRST_FRAME"
IMAGE_TO_VIDEO_ENDPOINT = "/api/v1/generation/image-to-video"
OMNI_VIDEO_ENDPOINT = "/api/v1/generation/omni-video"
PRODUCTION_MODEL = "seedance-2.0-fast"
PRODUCTION_RESOLUTION = "720p"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_rgb_sha256(path: str | Path) -> str:
    """Hash decoded RGB pixels plus dimensions before provider encoding."""
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        authority = width.to_bytes(8, "big") + height.to_bytes(8, "big") + rgb.tobytes()
    return hashlib.sha256(authority).hexdigest()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def requires_exact_first_frame(task: dict[str, Any]) -> bool:
    roles = task.get("reference_roles") or []
    return EXACT_FIRST_FRAME_ROLE in roles or bool(task.get("exact_first_frame_sha256"))


def _failure(code: str, task: dict[str, Any], **details: Any) -> dict[str, Any]:
    return {"code": code, "task_key": str(task.get("task_key") or "UNKNOWN"), **details}


def evaluate_task(task: dict[str, Any], *, root: str | Path) -> dict[str, Any]:
    """Validate the exact-frame transport contract without making a request."""
    root_path = Path(root).resolve()
    required = requires_exact_first_frame(task)
    failures: list[dict[str, Any]] = []
    if not required:
        return {
            "task_key": str(task.get("task_key") or "UNKNOWN"),
            "required": False,
            "status": "PASS",
            "endpoint": OMNI_VIDEO_ENDPOINT,
            "failures": [],
        }

    images = task.get("reference_images") or []
    shas = task.get("reference_sha256") or []
    roles = task.get("reference_roles") or []
    if not (len(images) == len(shas) == len(roles)):
        failures.append(_failure("EXACT_FIRST_FRAME_REFERENCE_BINDING_LENGTH_MISMATCH", task))
    exact_indices = [index for index, role in enumerate(roles) if role == EXACT_FIRST_FRAME_ROLE]
    if len(exact_indices) != 1:
        failures.append(_failure("EXACT_FIRST_FRAME_REQUIRES_EXACTLY_ONE_ROLE", task, count=len(exact_indices)))
        exact_index = None
    else:
        exact_index = exact_indices[0]

    exact_path: Path | None = None
    exact_sha = str(task.get("exact_first_frame_sha256") or "")
    if exact_index is not None and exact_index < len(images) and exact_index < len(shas):
        exact_path = _resolve(root_path, images[exact_index])
        if str(shas[exact_index]) != exact_sha:
            failures.append(_failure("EXACT_FIRST_FRAME_DECLARED_SHA_MISMATCH", task))
        if not exact_path.is_file():
            failures.append(_failure("EXACT_FIRST_FRAME_FILE_MISSING", task, path=str(images[exact_index])))
        elif _sha256(exact_path) != exact_sha:
            failures.append(_failure("EXACT_FIRST_FRAME_FILE_SHA_MISMATCH", task, path=str(images[exact_index])))

    if task.get("model") != PRODUCTION_MODEL:
        failures.append(_failure("EXACT_FIRST_FRAME_REQUIRES_FAST_MODEL", task, actual=task.get("model")))
    if task.get("resolution") != PRODUCTION_RESOLUTION:
        failures.append(_failure("EXACT_FIRST_FRAME_REQUIRES_720P", task, actual=task.get("resolution")))

    transport = task.get("video_transport")
    if not isinstance(transport, dict):
        failures.append(_failure("EXACT_FIRST_FRAME_TRANSPORT_CONTRACT_MISSING", task))
        transport = {}
    if transport.get("mode") != "image_to_video_start_frame":
        failures.append(_failure("EXACT_FIRST_FRAME_OMNI_REFERENCE_FORBIDDEN", task, actual=transport.get("mode")))
    if transport.get("endpoint") != IMAGE_TO_VIDEO_ENDPOINT:
        failures.append(_failure("EXACT_FIRST_FRAME_ENDPOINT_MUST_BE_IMAGE_TO_VIDEO", task, actual=transport.get("endpoint")))
    if transport.get("start_frame_sha256") != exact_sha:
        failures.append(_failure("EXACT_FIRST_FRAME_TRANSPORT_SHA_MISMATCH", task))
    if exact_path is not None and transport.get("start_frame_path") != images[exact_index]:
        failures.append(_failure("EXACT_FIRST_FRAME_TRANSPORT_PATH_MISMATCH", task))
    if transport.get("ordinary_images") not in (None, []):
        failures.append(_failure("EXACT_FIRST_FRAME_CANNOT_ALSO_USE_OMNI_IMAGES", task))
    if task.get("reference_audio_asset_ids") or task.get("exact_dialogue_audio_asset_ids"):
        failures.append(_failure("EXACT_FIRST_FRAME_NATIVE_ROUTE_CANNOT_CARRY_OMNI_AUDIO", task))

    authority = task.get("frame0_authority_contract")
    if not isinstance(authority, dict):
        failures.append(_failure("FRAME0_AUTHORITY_CONTRACT_MISSING", task))
        authority = {}
    if authority.get("source_sha256") != exact_sha:
        failures.append(_failure("FRAME0_AUTHORITY_SOURCE_SHA_MISMATCH", task))
    if authority.get("pre_encode_raw_rgb_sha256_required") is not True:
        failures.append(_failure("FRAME0_PRE_ENCODE_RAW_RGB_AUTHORITY_REQUIRED", task))
    expected_raw_rgb = authority.get("raw_rgb_sha256")
    if not expected_raw_rgb:
        failures.append(_failure("FRAME0_PRE_ENCODE_RAW_RGB_SHA_MISSING", task))
    elif exact_path is not None and exact_path.is_file():
        try:
            actual_raw_rgb = raw_rgb_sha256(exact_path)
        except Exception as exc:
            failures.append(_failure("FRAME0_PRE_ENCODE_IMAGE_DECODE_FAILED", task, error=str(exc)))
        else:
            if actual_raw_rgb != expected_raw_rgb:
                failures.append(_failure("FRAME0_PRE_ENCODE_RAW_RGB_SHA_MISMATCH", task, actual=actual_raw_rgb))

    post = task.get("post_harvest_exact_frame_gate")
    if not isinstance(post, dict):
        failures.append(_failure("POST_HARVEST_EXACT_FRAME_GATE_MISSING", task))
        post = {}
    if post.get("required") is not True:
        failures.append(_failure("POST_HARVEST_EXACT_FRAME_GATE_NOT_REQUIRED", task))
    if post.get("single_frame_prepend_allowed") is not False:
        failures.append(_failure("SINGLE_FRAME_PREPEND_MUST_BE_FORBIDDEN", task))
    if post.get("single_frame_replacement_allowed") is not False:
        failures.append(_failure("SINGLE_FRAME_REPLACEMENT_MUST_BE_FORBIDDEN", task))
    thresholds = post.get("frame0_thresholds") or {}
    if float(thresholds.get("minimum_ssim", 0.0)) < 0.98:
        failures.append(_failure("FRAME0_MINIMUM_SSIM_TOO_LOW", task))
    if float(thresholds.get("maximum_mae", 999.0)) > 3.0:
        failures.append(_failure("FRAME0_MAXIMUM_MAE_TOO_HIGH", task))
    if int(thresholds.get("maximum_phash_hamming", 999)) > 3:
        failures.append(_failure("FRAME0_MAXIMUM_PHASH_TOO_HIGH", task))
    if post.get("frame0_to_frame1_continuity_required") is not True:
        failures.append(_failure("FRAME0_TO_FRAME1_CONTINUITY_GATE_REQUIRED", task))

    return {
        "task_key": str(task.get("task_key") or "UNKNOWN"),
        "required": True,
        "status": "PASS" if not failures else "FAIL",
        "endpoint": IMAGE_TO_VIDEO_ENDPOINT,
        "start_frame_path": str(images[exact_index]) if exact_index is not None and exact_index < len(images) else None,
        "start_frame_sha256": exact_sha or None,
        "semantic_start_frame_verified": True,
        "pixel_exact_provider_output_guarantee": False,
        "failures": failures,
    }


def evaluate_batch(tasks: list[dict[str, Any]], *, root: str | Path) -> dict[str, Any]:
    rows = [evaluate_task(task, root=root) for task in tasks]
    failures = [failure for row in rows for failure in row["failures"]]
    return {
        "schema": "backlotos.exact_first_frame_transport_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "rows": rows,
        "failures": failures,
        "policy": "EXACT_FIRST_FRAME must use image-to-video start_frame. Omni images[] is reference-only. Provider output still requires frame0 authority and frame0-to-frame1 continuity QA; prepend/replace is never automatic repair.",
    }


def build_provider_request(
    task: dict[str, Any],
    *,
    prompt_text: str,
    root: str | Path,
    encode_image: Callable[[str], dict[str, str]],
) -> tuple[str, dict[str, Any]]:
    """Build the provider route and payload after fail-closed validation."""
    root_path = Path(root).resolve()
    exact = evaluate_task(task, root=root_path)
    common = {
        "prompt": prompt_text,
        "model": task.get("model"),
        "duration": int(task.get("duration_seconds", 0)),
        "aspect_ratio": task.get("aspect_ratio", "9:16"),
        "resolution": task.get("resolution"),
        "generating_count": 1,
    }
    if exact["required"]:
        if exact["status"] != "PASS":
            codes = ",".join(failure["code"] for failure in exact["failures"])
            raise ValueError(f"Exact-first-frame transport failed: {codes}")
        start = str(_resolve(root_path, str(exact["start_frame_path"])))
        return IMAGE_TO_VIDEO_ENDPOINT, {**common, "start_frame": encode_image(start)}

    images = [encode_image(str(_resolve(root_path, value))) for value in task.get("reference_images") or []]
    payload: dict[str, Any] = {**common, "images": images}
    audio_ids = [
        *(task.get("exact_dialogue_audio_asset_ids") or []),
        *(task.get("reference_audio_asset_ids") or []),
    ]
    if audio_ids:
        payload["audios"] = [{"asset_id": value} for value in audio_ids]
    return OMNI_VIDEO_ENDPOINT, payload


def transport_fingerprint(task: dict[str, Any]) -> str:
    contract = {
        "required": requires_exact_first_frame(task),
        "reference_roles": task.get("reference_roles") or [],
        "exact_first_frame_sha256": task.get("exact_first_frame_sha256"),
        "video_transport": task.get("video_transport"),
        "frame0_authority_contract": task.get("frame0_authority_contract"),
        "post_harvest_exact_frame_gate": task.get("post_harvest_exact_frame_gate"),
    }
    return hashlib.sha256(
        json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
