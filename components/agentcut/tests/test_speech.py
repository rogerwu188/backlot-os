from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentcut.agent import AgentServer
from agentcut.engine import AgentCutEngine
from agentcut.errors import ValidationError
from agentcut.speech import generate_speech, list_speech_voices, query_speech, submit_speech


class _Headers:
    def get(self, _name, default=None):
        return "audio/mpeg" if default is not None else None


class _Response:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode()
        self.headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        payload, self.payload = self.payload, b""
        return payload


class SpeechTests(unittest.TestCase):
    def test_requires_environment_credential(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValidationError, "GIGGLE_API_KEY"):
                submit_speech("line", voice_id="voice", emotion="neutral")

    def test_submit_does_not_return_secret(self):
        captured = {}

        def fake_open(request, timeout):
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data)
            captured["timeout"] = timeout
            return _Response({"code": 200, "data": {"task_id": "speech-123"}})

        with patch.dict(os.environ, {"GIGGLE_API_KEY": "test-secret"}, clear=True), \
             patch("agentcut.speech.urllib.request.urlopen", side_effect=fake_open):
            result = submit_speech("dramatic line", voice_id="voice-a", emotion="sad", speed=1.1)
        self.assertEqual(captured["payload"]["voice_id"], "voice-a")
        self.assertEqual(captured["payload"]["emotion"], "sad")
        self.assertEqual(captured["payload"]["speed"], 1.1)
        self.assertEqual(result["taskId"], "speech-123")
        self.assertNotIn("test-secret", json.dumps(result))
        self.assertTrue(result["commercialUseMetadata"]["releaseBlocked"])

    def test_list_voices_normalizes_provider_fields(self):
        response = {"code": 200, "data": [{"voice_id": "v1", "name": "Hero", "style": "calm", "gender": "female", "age": "youth", "language": "zh"}]}
        with patch.dict(os.environ, {"GIGGLE_API_KEY": "test-secret"}, clear=True), \
             patch("agentcut.speech.urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: _Response(response)):
            result = list_speech_voices()
        self.assertEqual(result["voices"][0]["voiceId"], "v1")
        self.assertNotIn("test-secret", json.dumps(result))

    def test_query_keeps_urls_private_at_ndjson_boundary(self):
        response = {"code": 200, "data": {"status": "completed", "urls": ["https://signed.invalid/a.mp3"]}}
        with patch.dict(os.environ, {"GIGGLE_API_KEY": "test-secret"}, clear=True), \
             patch("agentcut.speech.urllib.request.urlopen", side_effect=lambda *_args, **_kwargs: _Response(response)):
            direct = query_speech("task with space")
            server = AgentServer(AgentCutEngine(), workers=1)
            rpc = server.handle({"id": "q", "method": "querySpeech", "params": {"taskId": "task with space"}})
        self.assertEqual(direct["urlCount"], 1)
        self.assertNotIn("_urls", rpc["result"])
        self.assertNotIn("signed.invalid", json.dumps(rpc))

    def test_generate_polls_downloads_atomically_for_dialogue_track(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp).resolve() / "dialogue_voice.mp3"

            def fake_download(_url, path, overwrite):
                self.assertEqual(path, destination)
                self.assertFalse(overwrite)
                path.write_bytes(b"ID3speech")
                return {"path": str(path), "size": 9, "sha256": "a" * 64, "contentType": "audio/mpeg"}

            clock = iter([0.0, 1.0, 2.0, 3.0])
            with patch("agentcut.speech.submit_speech", return_value={
                    "capability": "AGENTCUT-SPEECH-001", "capabilityVersion": "1.0",
                    "status": "started", "taskId": "speech-123", "voiceId": "v1",
                    "emotion": "sad", "speed": 1, "textSha256": "b" * 64,
                    "commercialUseMetadata": {"present": False, "releaseBlocked": True},
                 }), patch("agentcut.speech.query_speech", return_value={
                    "status": "completed", "_urls": ["https://signed.invalid/a.mp3"],
                 }), patch("agentcut.speech._download", side_effect=fake_download), \
                 patch("agentcut.speech.time.sleep"), patch("agentcut.speech.time.monotonic", side_effect=clock):
                result = generate_speech(
                    "line", temp, voice_id="v1", emotion="sad",
                    poll_interval_seconds=2, timeout_seconds=10,
                )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["directTrackUse"]["track"], "Audio.Dialogue")
            self.assertFalse(result["releaseEligible"])
            self.assertIn("commercialRights", result["requiredPostGenerationGates"])
            self.assertNotIn("signed.invalid", json.dumps(result))

    def test_health_advertises_speech_capability(self):
        result = AgentServer(AgentCutEngine(), workers=1).handle({"id": "h", "method": "health", "params": {}})
        capability = result["result"]["capabilities"]["speechGeneration"]
        self.assertEqual(capability["generationMethod"], "generateSpeech")
        self.assertEqual(capability["credentialEnv"], "GIGGLE_API_KEY")
        self.assertEqual(capability["directTrack"], "Audio.Dialogue")

    def test_ndjson_errors_do_not_echo_secret(self):
        server = AgentServer(AgentCutEngine(), workers=1)
        output = io.StringIO()
        with patch.dict(os.environ, {"GIGGLE_API_KEY": "test-secret"}, clear=True), \
             patch("agentcut.speech.urllib.request.urlopen", side_effect=OSError("network unavailable")):
            server.serve(io.StringIO('{"id":"g","method":"generateSpeech","params":{"text":"x","voiceId":"v","emotion":"sad","outputDir":"/tmp"}}\n'), output)
        self.assertNotIn("test-secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
