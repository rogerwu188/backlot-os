import json

import pytest

from backlotos_producer_supervisor.giggle import GiggleError, generate_image, generate_video, health, task_status


def _capture(captured, response=None):
    def transport(request, timeout):
        captured.update({"url": request.full_url, "headers": dict(request.header_items()),
                         "body": json.loads(request.data.decode()) if request.data else None, "timeout": timeout})
        return response or {"data": {"task_id": "TASK-1"}}
    return transport


def test_health_fails_closed_without_key_and_reports_defaults(monkeypatch):
    monkeypatch.delenv("GIGGLE_API_KEY", raising=False)
    result = health()
    assert result["ok"] is False and result["status"] == "ADAPTER_REQUIRED"
    assert result["defaults"] == {"video_model": "seedance-2.0-fast", "image_model": "gpt2img"}


def test_image_defaults_to_gpt2img_and_does_not_echo_key(monkeypatch):
    monkeypatch.setenv("GIGGLE_API_KEY", "private-test-key")
    captured = {}
    result = generate_image({"prompt": "cinematic portrait"}, transport=_capture(captured))
    assert captured["url"].endswith("/api/v1/generation/text-to-image")
    assert captured["body"]["model"] == "gpt2img"
    assert captured["headers"]["X-auth"] == "private-test-key"
    assert "private-test-key" not in json.dumps(result)
    assert result["task_id"] == "TASK-1" and result["status"] == "SUBMITTED"


def test_video_defaults_to_seedance2_and_selects_endpoint(monkeypatch):
    monkeypatch.setenv("GIGGLE_API_KEY", "private-test-key")
    captured = {}
    result = generate_video({"prompt": "hero enters", "duration": 5}, transport=_capture(captured))
    assert captured["url"].endswith("/api/v1/generation/text-to-video")
    assert captured["body"]["model"] == "seedance-2.0-fast"
    assert result["model"] == "seedance-2.0-fast"
    captured = {}
    generate_video({"prompt": "hero enters", "duration": 5, "start_frame": {"url": "https://example.invalid/a.png"}}, transport=_capture(captured))
    assert captured["url"].endswith("/api/v1/generation/image-to-video")


def test_video_duration_and_model_are_validated_before_submission(monkeypatch):
    monkeypatch.setenv("GIGGLE_API_KEY", "private-test-key")
    with pytest.raises(GiggleError, match="between 4 and 15"):
        generate_video({"prompt": "x", "duration": 16}, transport=lambda *_: {})
    with pytest.raises(GiggleError, match="unsupported Seedance 2"):
        generate_video({"prompt": "x", "model": "other", "duration": 5}, transport=lambda *_: {})
    with pytest.raises(GiggleError, match="unsupported Seedance 2"):
        generate_video({"prompt": "x", "model": "seedance-2.0-pro", "duration": 5}, transport=lambda *_: {})


def test_task_query_is_read_only_get(monkeypatch):
    monkeypatch.setenv("GIGGLE_API_KEY", "private-test-key")
    captured = {}
    result = task_status({"task_id": "T 1"}, transport=_capture(captured, {"data": {"status": "processing"}}))
    assert "task_id=T+1" in captured["url"] and captured["body"] is None
    assert result["task_id"] == "T 1"
