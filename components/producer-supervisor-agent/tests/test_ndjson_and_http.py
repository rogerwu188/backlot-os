import io
import json
import threading
import time
import urllib.error
import urllib.request

from backlotos_producer_supervisor.http_server import TaskServer
from backlotos_producer_supervisor.invoker import AgentInvoker
from backlotos_producer_supervisor.runtime import Runtime


def test_ndjson_roundtrip():
    r = Runtime()
    inp = io.StringIO('{"verb":"health"}\n{"verb":"publish"}\n')
    out = io.StringIO()
    r.serve_ndjson(inp, out)
    lines = [json.loads(l) for l in out.getvalue().strip().splitlines()]
    assert len(lines) == 2
    assert lines[0]["ok"] is True
    assert lines[1]["status"] == "BLOCKED"


def test_http_health_and_task_roundtrip():
    r = Runtime(AgentInvoker(mock_fn=lambda a, p: {"ok": True, "status": "COMPLETE"}))
    server = TaskServer(("127.0.0.1", 0), r)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            health = json.loads(resp.read())
        assert health["ok"] is True
        assert health["status"] == "ready"
        assert health["version"]

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/missing", timeout=5)
            assert False, "expected 404"
        except urllib.error.HTTPError as exc:
            assert exc.code == 404

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/task",
            data=json.dumps({"verb": "validate", "intake": {}}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                code = resp.getcode()
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            code = exc.code
            body = json.loads(exc.read())
        assert code in (200, 422)
        assert body["ok"] is False  # empty intake fails validation
        assert body["verb"] == "validate"

        # irreversible verb over HTTP must still be blocked
        req2 = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/task",
            data=json.dumps({"verb": "publish", "params": {"force": True}}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            urllib.request.urlopen(req2, timeout=5)
            assert False, "expected HTTPError for 422 status"
        except urllib.error.HTTPError as exc:
            body2 = json.loads(exc.read())
            assert body2["status"] == "BLOCKED"
    finally:
        server.shutdown()
        server.server_close()
