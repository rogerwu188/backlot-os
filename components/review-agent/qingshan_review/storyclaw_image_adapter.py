"""Exact-SHA image review through StoryClaw's Chat Completions endpoint."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any


REQUIRED_CHECKS = (
    "canonical_identity_continuity",
    "scene_authority",
    "story_action_clarity",
    "no_text_or_pseudotext",
    "no_extra_or_duplicated_bodies",
    "native_anatomy",
)
DEFAULT_ENDPOINT = "https://llm.storyclaw.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-5.5"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _extract_json(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        value = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model response did not contain a JSON object")
    data = json.loads(value[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model response JSON must be an object")
    return data


def _message_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("StoryClaw response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "\n".join(parts)
    raise ValueError("StoryClaw response has no textual message content")


def _normalize_result(
    model_result: dict[str, Any],
    *,
    candidate_sha256: str,
    source_id: str,
    episode: str,
    model: str,
    response_id: str | None,
) -> dict[str, Any]:
    raw_checks = model_result.get("checks")
    if not isinstance(raw_checks, dict):
        raise ValueError("model result checks must be an object")
    checks: dict[str, str] = {}
    for name in REQUIRED_CHECKS:
        status = str(raw_checks.get(name, "")).upper()
        if status not in {"PASS", "FAIL"}:
            raise ValueError(f"model result missing valid check: {name}")
        checks[name] = status

    try:
        confidence = max(0.0, min(1.0, float(model_result.get("confidence"))))
    except (TypeError, ValueError):
        raise ValueError("model result confidence must be numeric") from None
    if confidence < 0.5:
        raise ValueError("model confidence below evidence admission floor")

    findings = model_result.get("findings")
    if not isinstance(findings, list):
        findings = []
    normalized_findings = [str(item)[:1000] for item in findings if str(item).strip()]

    regions = model_result.get("regions")
    normalized_regions = []
    if isinstance(regions, list):
        for region in regions:
            if not isinstance(region, dict):
                continue
            label = str(region.get("label", "finding")).strip()[:120]
            description = str(region.get("description", "")).strip()[:1000]
            if description:
                normalized_regions.append({"label": label, "description": description})

    status = "FAIL" if "FAIL" in checks.values() else "PASS"
    summary = str(model_result.get("summary", "")).strip()[:2000]
    return {
        "schema": "qingshan.image_visual_adjudication.v1",
        "episode": episode,
        "status": status,
        "confidence": round(confidence, 6),
        "summary": summary or "StoryClaw GPT visual adjudication completed.",
        "required_checks": list(REQUIRED_CHECKS),
        "evidence": [
            {
                "source_id": source_id,
                "sha256": candidate_sha256,
                "checks": checks,
                "findings": normalized_findings,
                "regions": normalized_regions,
            }
        ],
        "provider": {
            "name": "storyclaw",
            "protocol": "chat_completions",
            "model": model,
            "response_id": response_id,
        },
        "rollback": "Preserve the original candidate and this immutable evidence result.",
    }


def _request_payload(path: Path, request: dict[str, Any], model: str) -> dict[str, Any]:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    metadata = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
    focus = request.get("review_focus") if isinstance(request.get("review_focus"), dict) else {}
    instructions = {
        "candidate_sha256": request["candidate_sha256"],
        "metadata": metadata,
        "review_focus": focus,
        "required_checks": list(REQUIRED_CHECKS),
        "output_contract": {
            "status": "PASS or FAIL",
            "confidence": "0..1",
            "summary": "short factual summary",
            "checks": {name: "PASS or FAIL" for name in REQUIRED_CHECKS},
            "findings": ["specific visible defect or empty"],
            "regions": [{"label": "region label", "description": "location and evidence"}],
        },
    }
    system = (
        "You are BacklotOS's evidence-bound film still reviewer. Inspect only the supplied image. "
        "Be strict about readable text or pseudotext, anatomy, duplicated bodies, identity/wardrobe "
        "continuity cues, scene consistency, and whether the intended action is visually legible. "
        "Do not invent unseen references. Return one JSON object only, with every required check."
    )
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": 1800,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": json.dumps(instructions, ensure_ascii=False)},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                ],
            },
        ],
    }


def main() -> int:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or request.get("schema") != "qingshan.image_visual_runtime.request.v1":
            raise ValueError("invalid runtime request schema")
        path = Path(str(request.get("path", ""))).expanduser().resolve()
        if not path.is_file():
            raise ValueError("candidate image does not exist")
        digest = _sha256(path)
        if request.get("candidate_sha256") != digest:
            raise ValueError("candidate SHA-256 mismatch")

        api_key = os.environ.get("BACKLOT_STORYCLAW_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("BACKLOT_STORYCLAW_API_KEY is not configured")
        endpoint = os.environ.get("BACKLOT_STORYCLAW_API_BASE", DEFAULT_ENDPOINT).strip()
        if endpoint != DEFAULT_ENDPOINT and not endpoint.startswith("https://"):
            raise ValueError("StoryClaw API endpoint must use HTTPS")
        model = os.environ.get("BACKLOT_STORYCLAW_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        payload = _request_payload(path, request, model)
        http_request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        timeout = float(os.environ.get("BACKLOT_STORYCLAW_TIMEOUT_SECONDS", "180"))
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            raw_response = json.loads(response.read().decode("utf-8"))
        model_result = _extract_json(_message_text(raw_response))
        metadata = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
        source_id = str(
            metadata.get("source_id") or metadata.get("beat_id") or metadata.get("clip_id") or path.stem
        )
        episode = str(metadata.get("episode") or "")
        result = _normalize_result(
            model_result,
            candidate_sha256=digest,
            source_id=source_id,
            episode=episode,
            model=model,
            response_id=str(raw_response.get("id")) if raw_response.get("id") else None,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema": "qingshan.image_visual_runtime.error.v1",
                    "status": "ERROR",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
