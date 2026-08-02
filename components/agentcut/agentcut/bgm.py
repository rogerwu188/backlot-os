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


CAPABILITY_ID = "AGENTCUT-BGM-001"
CAPABILITY_VERSION = "1.0"
BASE_URL = "https://giggle.pro"
GENERATE_ENDPOINT = "/api/v1/generation/generate-music"
QUERY_ENDPOINT = "/api/v1/generation/task/query"
TERMINAL = {"completed", "failed"}


def _api_key() -> str:
    value = os.environ.get("GIGGLE_API_KEY", "")
    if not value:
        raise ValidationError("GIGGLE_API_KEY is not configured in the process environment")
    return value


def _request(method: str, endpoint: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        BASE_URL + endpoint, data=body, method=method,
        headers={"x-auth": _api_key(), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Giggle BGM request failed: {exc}") from exc
    if not isinstance(result, dict) or result.get("code") != 200:
        message = result.get("msg", "invalid response") if isinstance(result, dict) else "invalid response"
        raise ValidationError(f"Giggle BGM API error: {message}")
    return result


def _validate_prompt(prompt: Any) -> str:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValidationError("prompt must be a non-empty string")
    if len(prompt) > 10_000:
        raise ValidationError("prompt exceeds 10,000 characters")
    return prompt


def submit_bgm(prompt: str, *, instrumental: bool = True) -> dict[str, Any]:
    prompt = _validate_prompt(prompt)
    if instrumental is not True:
        raise ValidationError("AgentCut BGM generation requires instrumental=true; vocals are not allowed")
    result = _request("POST", GENERATE_ENDPOINT, payload={"prompt": prompt, "instrumental": True})
    task_id = (result.get("data") or {}).get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise ValidationError("Giggle BGM response did not include task_id")
    return {
        "capability": CAPABILITY_ID, "capabilityVersion": CAPABILITY_VERSION,
        "status": "started", "taskId": task_id, "instrumental": True,
        "promptSha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "commercialUseMetadata": {"present": False, "releaseBlocked": True},
    }


def query_bgm(task_id: str) -> dict[str, Any]:
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValidationError("taskId must be a non-empty string")
    result = _request("GET", f"{QUERY_ENDPOINT}?task_id={urllib.parse.quote(task_id)}")
    data = result.get("data") or {}
    urls = data.get("urls") or []
    return {
        "capability": CAPABILITY_ID, "capabilityVersion": CAPABILITY_VERSION,
        "taskId": task_id, "status": data.get("status"), "urlCount": len(urls),
        "error": data.get("err_msg") or None,
        "commercialUseMetadata": {"present": False, "releaseBlocked": True},
        "_urls": urls,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path, *, overwrite: bool) -> dict[str, Any]:
    if destination.exists() and not overwrite:
        raise ValidationError(f"BGM output exists (use overwrite): {destination}")
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
            raise ValidationError("Giggle BGM download returned an empty file")
        os.replace(temp_path, destination)
        return {"path": str(destination), "size": destination.stat().st_size,
                "sha256": _sha256(destination), "contentType": content_type}
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def generate_bgm(
    prompt: str, output_dir: str | Path, *, poll_interval_seconds: float = 20,
    timeout_seconds: float = 1500, overwrite: bool = False,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not 15 <= poll_interval_seconds <= 60:
        raise ValidationError("pollIntervalSeconds must be between 15 and 60")
    if not 30 <= timeout_seconds <= 1500:
        raise ValidationError("timeoutSeconds must be between 30 and 1500")
    output = Path(output_dir).expanduser().resolve()
    submitted = submit_bgm(prompt, instrumental=True)
    task_id = submitted["taskId"]
    started = time.monotonic()
    if progress:
        progress({"phase": "bgm_submitted", "taskId": task_id, "status": "started"})
    while True:
        elapsed = time.monotonic() - started
        if elapsed >= timeout_seconds:
            return {**submitted, "status": "timeout", "elapsedSeconds": round(elapsed, 3),
                    "files": [], "releaseEligible": False}
        time.sleep(poll_interval_seconds)
        queried = query_bgm(task_id)
        status = queried["status"]
        if progress:
            progress({"phase": "bgm_poll", "taskId": task_id, "status": status,
                      "elapsedSeconds": round(time.monotonic() - started, 3)})
        if status == "failed":
            return {**submitted, "status": "failed", "error": queried["error"], "files": [],
                    "elapsedSeconds": round(time.monotonic() - started, 3), "releaseEligible": False}
        if status == "completed":
            urls = queried.pop("_urls")
            if not urls:
                raise ValidationError("Giggle BGM completed without audio URLs")
            files = [_download(url, output / f"bgm_candidate_{index}.mp3", overwrite=overwrite)
                     for index, url in enumerate(urls, 1)]
            return {**submitted, "status": "completed", "urlCount": len(urls), "files": files,
                    "elapsedSeconds": round(time.monotonic() - started, 3), "releaseEligible": False,
                    "requiredPostGenerationGates": ["mediaProbe", "noVocals", "loopability", "loudness", "humanListen", "commercialRights"]}
