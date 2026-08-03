from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qingshan_review.core import Reviewer
from qingshan_review.storyclaw_image_adapter import (
    DEFAULT_ENDPOINT,
    REQUIRED_CHECKS,
    _extract_json,
    _normalize_result,
    main,
)


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class StoryClawImageAdapterTests(unittest.TestCase):
    def test_extracts_fenced_json(self) -> None:
        self.assertEqual(_extract_json("```json\n{\"status\":\"PASS\"}\n```"), {"status": "PASS"})

    def test_normalization_binds_local_sha_and_preserves_failures(self) -> None:
        checks = {name: "PASS" for name in REQUIRED_CHECKS}
        checks["native_anatomy"] = "FAIL"
        result = _normalize_result(
            {
                "confidence": 0.94,
                "summary": "hand anatomy is invalid",
                "checks": checks,
                "findings": ["six fingers on left hand"],
                "regions": [{"label": "left hand", "description": "lower-right hand has six digits"}],
            },
            candidate_sha256="a" * 64,
            source_id="SHOT-1",
            episode="E01",
            model="gpt-5.5",
            response_id="resp-1",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["evidence"][0]["sha256"], "a" * 64)
        self.assertEqual(result["evidence"][0]["checks"]["native_anatomy"], "FAIL")

    def test_main_uses_storyclaw_endpoint_without_leaking_key(self) -> None:
        checks = {name: "PASS" for name in REQUIRED_CHECKS}
        model_json = {
            "confidence": 0.97,
            "summary": "all required checks pass",
            "checks": checks,
            "findings": [],
            "regions": [],
        }
        response = {
            "id": "sc-test",
            "choices": [{"message": {"content": json.dumps(model_json)}}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "candidate.png"
            image.write_bytes(PNG)
            digest = hashlib.sha256(PNG).hexdigest()
            request = {
                "schema": "qingshan.image_visual_runtime.request.v1",
                "path": str(image),
                "candidate_sha256": digest,
                "metadata": {"episode": "E01", "source_id": "S1"},
            }
            captured = {}

            def fake_urlopen(http_request, timeout):
                captured["url"] = http_request.full_url
                captured["authorization"] = http_request.headers.get("Authorization")
                captured["timeout"] = timeout
                return FakeResponse(response)

            stdin = io.StringIO(json.dumps(request))
            stdout = io.StringIO()
            with patch.dict(os.environ, {"BACKLOT_STORYCLAW_API_KEY": "unit-test-secret"}, clear=True):
                with patch("qingshan_review.storyclaw_image_adapter.urllib.request.urlopen", fake_urlopen):
                    with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
                        code = main()
            result = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(captured["url"], DEFAULT_ENDPOINT)
        self.assertEqual(captured["authorization"], "Bearer unit-test-secret")
        self.assertEqual(result["evidence"][0]["sha256"], digest)
        self.assertNotIn("unit-test-secret", stdout.getvalue())

    def test_missing_key_fails_as_capability_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "candidate.png"
            image.write_bytes(PNG)
            request = {
                "schema": "qingshan.image_visual_runtime.request.v1",
                "path": str(image),
                "candidate_sha256": hashlib.sha256(PNG).hexdigest(),
            }
            with patch.dict(os.environ, {}, clear=True):
                with patch("sys.stdin", io.StringIO(json.dumps(request))), patch("sys.stdout", io.StringIO()) as out:
                    code = main()
                    result = json.loads(out.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("not configured", result["error"])

    def test_reviewer_auto_selects_bundled_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "candidate.png"
            image.write_bytes(PNG)
            checks = {name: "PASS" for name in REQUIRED_CHECKS}
            adapter_result = {
                "schema": "qingshan.image_visual_adjudication.v1",
                "confidence": 0.96,
                "evidence": [{"sha256": hashlib.sha256(PNG).hexdigest(), "checks": checks}],
            }
            completed = __import__("subprocess").CompletedProcess(
                [], 0, json.dumps(adapter_result), ""
            )
            with patch.dict(os.environ, {"BACKLOT_STORYCLAW_API_KEY": "secret"}, clear=True):
                with patch("qingshan_review.core.subprocess.run", return_value=completed) as run:
                    live, error = Reviewer(production_root=tmp)._run_image_visual_adapter(image, {})
        self.assertIsNone(error)
        self.assertEqual(live["schema"], "qingshan.image_visual_adjudication.v1")
        self.assertEqual(
            run.call_args.args[0][1:], ["-m", "qingshan_review.storyclaw_image_adapter"]
        )


if __name__ == "__main__":
    unittest.main()
