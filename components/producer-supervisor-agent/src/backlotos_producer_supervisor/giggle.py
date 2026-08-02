"""Giggle image/video generation adapter.

The API credential is accepted only through ``GIGGLE_API_KEY``.  Generation
POSTs are deliberately not retried: a lost response may still represent a
charged task, so the caller must reconcile it before resubmitting.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

DEFAULT_BASE_URL = "https://giggle.pro"
DEFAULT_VIDEO_MODEL = "seedance-2.0-pro"
DEFAULT_IMAGE_MODEL = "gpt2img"
VIDEO_MODELS = {"seedance-2.0-pro", "seedance-2.0-fast", "seedance-2.0-mini"}


class GiggleError(RuntimeError):
    pass


def _configured_key() -> str:
    value = os.environ.get("GIGGLE_API_KEY", "").strip()
    if not value or value in {"changeme", "your-key-here"}:
        raise GiggleError("GIGGLE_API_KEY is not configured")
    return value


def health() -> dict:
    try:
        _configured_key()
        key_present = True
    except GiggleError:
        key_present = False
    return {
        "ok": key_present,
        "status": "ready" if key_present else "ADAPTER_REQUIRED",
        "provider": "giggle",
        "credential_env": "GIGGLE_API_KEY",
        "api_key_present": key_present,
        "base_url": os.environ.get("GIGGLE_API_BASE", DEFAULT_BASE_URL).rstrip("/"),
        "defaults": {"video_model": DEFAULT_VIDEO_MODEL, "image_model": DEFAULT_IMAGE_MODEL},
        "capabilities": {"image_generation": key_present, "video_generation": key_present, "task_status": key_present},
    }


def _default_transport(request: urllib.request.Request, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Do not expose upstream bodies: providers sometimes echo requests.
        raise GiggleError(f"Giggle API returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GiggleError(f"Giggle API request failed ({type(exc).__name__})") from None


def _request(path: str, *, payload: dict | None = None, query: dict | None = None,
             transport: Callable[[urllib.request.Request, float], dict] | None = None) -> dict:
    base = os.environ.get("GIGGLE_API_BASE", DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"Accept": "application/json", "Content-Type": "application/json", "x-auth": _configured_key()}
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST" if payload is not None else "GET")
    result = (transport or _default_transport)(request, float(os.environ.get("GIGGLE_API_TIMEOUT_SECONDS", "30")))
    if not isinstance(result, dict):
        raise GiggleError("Giggle API returned a non-object response")
    return result


def _receipt(kind: str, endpoint: str, model: str, response: dict) -> dict:
    key = os.environ.get("GIGGLE_API_KEY", "")
    def sanitize(value):
        if isinstance(value, dict):
            return {k: sanitize(v) for k, v in value.items() if k.lower() not in {"x-auth", "authorization", "api_key"}}
        if isinstance(value, list):
            return [sanitize(v) for v in value]
        if isinstance(value, str) and key:
            return value.replace(key, "[REDACTED]")
        return value
    response = sanitize(response)
    data = response.get("data") if isinstance(response.get("data"), dict) else response
    task_id = data.get("task_id") or data.get("taskId") or data.get("id")
    return {
        "ok": bool(task_id),
        "status": "SUBMITTED" if task_id else "ERROR",
        "provider": "giggle",
        "kind": kind,
        "model": model,
        "endpoint": endpoint,
        "task_id": str(task_id) if task_id is not None else None,
        "provider_response": response,
        "credential_env": "GIGGLE_API_KEY",
        "credential_exposed": False,
    }


def generate_image(params: dict, *, transport=None) -> dict:
    prompt = str(params.get("prompt", "")).strip()
    if not prompt:
        raise GiggleError("prompt is required")
    model = str(params.get("model") or os.environ.get("GIGGLE_IMAGE_MODEL") or DEFAULT_IMAGE_MODEL)
    references = params.get("reference_images") or []
    if not isinstance(references, list):
        raise GiggleError("reference_images must be a list")
    endpoint = "/api/v1/generation/image-to-image" if references else "/api/v1/generation/text-to-image"
    payload = {
        "prompt": prompt,
        "model": model,
        "aspect_ratio": params.get("aspect_ratio", "9:16"),
        "resolution": params.get("resolution", "1K"),
        "generate_count": int(params.get("count", 1)),
        "watermark": bool(params.get("watermark", False)),
    }
    if references:
        payload["reference_images"] = references
    return _receipt("image", endpoint, model, _request(endpoint, payload=payload, transport=transport))


def generate_video(params: dict, *, transport=None) -> dict:
    prompt = str(params.get("prompt", "")).strip()
    if not prompt:
        raise GiggleError("prompt is required")
    model = str(params.get("model") or os.environ.get("GIGGLE_VIDEO_MODEL") or DEFAULT_VIDEO_MODEL)
    if model not in VIDEO_MODELS:
        raise GiggleError(f"unsupported Seedance 2 model: {model}")
    duration = int(params.get("duration", params.get("duration_seconds", 4)))
    if not 4 <= duration <= 15:
        raise GiggleError("Seedance 2 duration must be between 4 and 15 seconds")
    start_frame, end_frame = params.get("start_frame"), params.get("end_frame")
    endpoint = "/api/v1/generation/image-to-video" if start_frame or end_frame else "/api/v1/generation/text-to-video"
    payload: dict[str, Any] = {
        "prompt": prompt, "model": model, "duration": duration,
        "aspect_ratio": params.get("aspect_ratio", "9:16"),
        "resolution": params.get("resolution", "720p"),
        "generating_count": int(params.get("count", 1)),
    }
    if start_frame:
        payload["start_frame"] = start_frame
    if end_frame:
        payload["end_frame"] = end_frame
    return _receipt("video", endpoint, model, _request(endpoint, payload=payload, transport=transport))


def task_status(params: dict, *, transport=None) -> dict:
    task_id = str(params.get("task_id", "")).strip()
    if not task_id:
        raise GiggleError("task_id is required")
    response = _request("/api/v1/generation/task/query", query={"task_id": task_id}, transport=transport)
    return {"ok": True, "status": "OK", "provider": "giggle", "task_id": task_id,
            "provider_response": response, "credential_exposed": False}
