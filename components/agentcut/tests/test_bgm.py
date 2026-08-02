from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentcut.agent import AgentServer
from agentcut.bgm import generate_bgm, query_bgm, submit_bgm
from agentcut.engine import AgentCutEngine
from agentcut.errors import ValidationError


class _Response:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        payload, self.payload = self.payload, b""
        return payload


class BgmTests(unittest.TestCase):
    def test_requires_environment_credential(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValidationError, "GIGGLE_API_KEY"):
                submit_bgm("quiet instrumental underscore")

    def test_submit_is_instrumental_and_does_not_return_secret(self):
        captured = {}

        def fake_open(request, timeout):
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data)
            captured["timeout"] = timeout
            return _Response({"code": 200, "data": {"task_id": "task-123"}})

        with patch.dict(os.environ, {"GIGGLE_API_KEY": "test-secret"}, clear=True), \
             patch("agentcut.bgm.urllib.request.urlopen", side_effect=fake_open):
            result = submit_bgm("quiet instrumental underscore")
        self.assertEqual(captured["payload"]["instrumental"], True)
        self.assertEqual(result["taskId"], "task-123")
        self.assertNotIn("test-secret", json.dumps(result))
        self.assertTrue(result["commercialUseMetadata"]["releaseBlocked"])

    def test_query_keeps_urls_private_at_ndjson_boundary(self):
        response = {"code": 200, "data": {"status": "completed", "urls": ["https://signed.invalid/a.mp3"]}}
        with patch.dict(os.environ, {"GIGGLE_API_KEY": "test-secret"}, clear=True), \
             patch("agentcut.bgm.urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: _Response(response)):
            direct = query_bgm("task with space")
            server = AgentServer(AgentCutEngine(), workers=1)
            rpc = server.handle({"id": "q", "method": "queryBgm", "params": {"taskId": "task with space"}})
        self.assertEqual(direct["urlCount"], 1)
        self.assertNotIn("_urls", rpc["result"])
        self.assertNotIn("signed.invalid", json.dumps(rpc))

    def test_generate_polls_downloads_atomically_and_reports_release_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp).resolve() / "bgm_candidate_1.mp3"

            def fake_download(_url, path, overwrite):
                self.assertEqual(path, destination)
                self.assertFalse(overwrite)
                path.write_bytes(b"ID3test")
                return {"path": str(path), "size": 7, "sha256": "a" * 64, "contentType": "audio/mpeg"}

            clock = iter([0.0, 1.0, 2.0, 3.0])
            with patch("agentcut.bgm.submit_bgm", return_value={
                    "capability": "AGENTCUT-BGM-001", "capabilityVersion": "1.0",
                    "status": "started", "taskId": "task-123", "instrumental": True,
                    "promptSha256": "b" * 64,
                    "commercialUseMetadata": {"present": False, "releaseBlocked": True},
                 }), patch("agentcut.bgm.query_bgm", return_value={
                    "status": "completed", "_urls": ["https://signed.invalid/a.mp3"],
                 }), patch("agentcut.bgm._download", side_effect=fake_download), \
                 patch("agentcut.bgm.time.sleep"), patch("agentcut.bgm.time.monotonic", side_effect=clock):
                result = generate_bgm("instrumental", temp, poll_interval_seconds=15, timeout_seconds=30)
            self.assertEqual(result["status"], "completed")
            self.assertFalse(result["releaseEligible"])
            self.assertIn("commercialRights", result["requiredPostGenerationGates"])
            self.assertNotIn("signed.invalid", json.dumps(result))

    def test_health_advertises_bgm_capability(self):
        result = AgentServer(AgentCutEngine(), workers=1).handle({"id": "h", "method": "health", "params": {}})
        capability = result["result"]["capabilities"]["bgmGeneration"]
        self.assertEqual(capability["generationMethod"], "generateBgm")
        self.assertEqual(capability["credentialEnv"], "GIGGLE_API_KEY")
        self.assertTrue(capability["commercialMetadataRequiredForRelease"])

    def test_ndjson_errors_do_not_echo_secret(self):
        server = AgentServer(AgentCutEngine(), workers=1)
        output = io.StringIO()
        with patch.dict(os.environ, {"GIGGLE_API_KEY": "test-secret"}, clear=True), \
             patch("agentcut.bgm.urllib.request.urlopen", side_effect=OSError("network unavailable")):
            server.serve(io.StringIO('{"id":"g","method":"generateBgm","params":{"prompt":"x","outputDir":"/tmp"}}\n'), output)
        self.assertNotIn("test-secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
