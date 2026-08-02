from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .errors import ValidationError


CAPABILITY_ID = "AGENTCUT-SPEECH-001"
CAPABILITY_VERSION = "1.0"
BASE_URL = "https://giggle.pro"
GENERATE_ENDPOINT = "/api/v1/generation/text-to-audio"
QUERY_ENDPOINT = "/api/v1/generation/task/query"
VOICES_ENDPOINT = "/api/v1/project/preset_tones"


def _api_key() -> str:
    value = os.environ.get("GIGGLE_API_KEY", "")
    if not value:
        raise ValidationError("GIGGLE_API_KEY is not configured in the process environment")
    return value


def _request(method: str, endpoint: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        BASE_URL + endpoint, data=body, method=method,
        headers={
            "x-auth": _api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "python-requests/2.32.5",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Giggle speech request failed: {exc}") from exc
    if not isinstance(result, dict) or result.get("code") != 200:
        message = result.get("msg", "invalid response") if isinstance(result, dict) else "invalid response"
        raise ValidationError(f"Giggle speech API error: {message}")
    return result


def _validate_text(text: Any) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValidationError("text must be a non-empty string")
    if len(text) > 10_000:
        raise ValidationError("text exceeds 10,000 characters")
    return text


def _validate_non_empty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string")
    return value.strip()


def _validate_speed(speed: Any) -> float:
    try:
        result = float(speed)
    except (TypeError, ValueError) as exc:
        raise ValidationError("speed must be a number") from exc
    if not 0.5 <= result <= 2.0:
        raise ValidationError("speed must be between 0.5 and 2.0")
    return result


def list_speech_voices() -> dict[str, Any]:
    result = _request("GET", VOICES_ENDPOINT)
    voices = result.get("data") or []
    if not isinstance(voices, list):
        raise ValidationError("Giggle speech voices response was invalid")
    normalized = []
    for voice in voices:
        if not isinstance(voice, dict):
            continue
        normalized.append({
            "voiceId": voice.get("voice_id") or voice.get("voiceId"),
            "name": voice.get("name"),
            "style": voice.get("style"),
            "gender": voice.get("gender"),
            "age": voice.get("age"),
            "language": voice.get("language"),
        })
    return {"capability": CAPABILITY_ID, "capabilityVersion": CAPABILITY_VERSION, "voices": normalized}


def submit_speech(text: str, *, voice_id: str, emotion: str, speed: float = 1.0) -> dict[str, Any]:
    text = _validate_text(text)
    voice_id = _validate_non_empty(voice_id, "voiceId")
    emotion = _validate_non_empty(emotion, "emotion")
    speed = _validate_speed(speed)
    payload = {"text": text, "voice_id": voice_id, "emotion": emotion, "speed": speed}
    result = _request("POST", GENERATE_ENDPOINT, payload=payload)
    task_id = (result.get("data") or {}).get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise ValidationError("Giggle speech response did not include task_id")
    return {
        "capability": CAPABILITY_ID, "capabilityVersion": CAPABILITY_VERSION,
        "status": "started", "taskId": task_id, "voiceId": voice_id,
        "emotion": emotion, "speed": speed,
        "textSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "commercialUseMetadata": {"present": False, "releaseBlocked": True},
    }


def query_speech(task_id: str) -> dict[str, Any]:
    task_id = _validate_non_empty(task_id, "taskId")
    result = _request("GET", f"{QUERY_ENDPOINT}?task_id={urllib.parse.quote(task_id)}")
    data = result.get("data") or {}
    urls = data.get("urls") or []
    return {
        "capability": CAPABILITY_ID, "capabilityVersion": CAPABILITY_VERSION,
        "taskId": task_id, "status": data.get("status"), "urlCount": len(urls),
        "error": data.get("err_msg") or None,
        "commercialUseMetadata": {"present": False, "releaseBlocked": True},
        "_urls": [url.replace("~", "%7E") for url in urls if isinstance(url, str)],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path, *, overwrite: bool) -> dict[str, Any]:
    if destination.exists() and not overwrite:
        raise ValidationError(f"speech output exists (use overwrite): {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False) as temp:
                temp_name = temp.name
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    temp.write(chunk)
        temp_path = Path(temp_name)
        if temp_path.stat().st_size == 0:
            raise ValidationError("Giggle speech download returned an empty file")
        os.replace(temp_path, destination)
        return {
            "path": str(destination), "size": destination.stat().st_size,
            "sha256": _sha256(destination), "contentType": content_type,
        }
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def generate_speech(
    text: str, output_dir: str | Path, *, voice_id: str, emotion: str, speed: float = 1.0,
    poll_interval_seconds: float = 5, timeout_seconds: float = 120, overwrite: bool = False,
    file_name: str = "dialogue_voice.mp3",
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not 2 <= poll_interval_seconds <= 30:
        raise ValidationError("pollIntervalSeconds must be between 2 and 30")
    if not 10 <= timeout_seconds <= 600:
        raise ValidationError("timeoutSeconds must be between 10 and 600")
    if Path(file_name).name != file_name or not file_name.lower().endswith(".mp3"):
        raise ValidationError("fileName must be a local .mp3 file name")
    output = Path(output_dir).expanduser().resolve()
    submitted = submit_speech(text, voice_id=voice_id, emotion=emotion, speed=speed)
    task_id = submitted["taskId"]
    started = time.monotonic()
    if progress:
        progress({"phase": "speech_submitted", "taskId": task_id, "status": "started"})
    while True:
        elapsed = time.monotonic() - started
        if elapsed >= timeout_seconds:
            return {**submitted, "status": "timeout", "elapsedSeconds": round(elapsed, 3),
                    "file": None, "releaseEligible": False}
        time.sleep(poll_interval_seconds)
        queried = query_speech(task_id)
        status = queried["status"]
        if progress:
            progress({"phase": "speech_poll", "taskId": task_id, "status": status,
                      "elapsedSeconds": round(time.monotonic() - started, 3)})
        if status == "failed":
            return {**submitted, "status": "failed", "error": queried["error"], "file": None,
                    "elapsedSeconds": round(time.monotonic() - started, 3), "releaseEligible": False}
        if status == "completed":
            urls = queried.pop("_urls")
            if not urls:
                raise ValidationError("Giggle speech completed without audio URL")
            file_receipt = _download(urls[0], output / file_name, overwrite=overwrite)
            return {**submitted, "status": "completed", "urlCount": len(urls), "file": file_receipt,
                    "elapsedSeconds": round(time.monotonic() - started, 3), "releaseEligible": False,
                    "directTrackUse": {"track": "Audio.Dialogue", "source": file_receipt["path"]},
                    "requiredPostGenerationGates": ["mediaProbe", "dialogueTiming", "humanListen", "commercialRights"]}
