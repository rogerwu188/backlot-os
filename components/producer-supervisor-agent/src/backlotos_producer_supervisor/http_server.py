"""Minimal stdlib-only HTTP server: GET /health, POST /v1/task.

Wire format matches backlotos_launcher.agent_host.RoleServer/RoleHandler
exactly, so this package can run as its own standalone HTTP agent (outside
the launcher's external-command proxy) with a compatible surface.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .runtime import Runtime


class TaskServer(ThreadingHTTPServer):
    def __init__(self, address, runtime: Runtime):
        super().__init__(address, TaskHandler)
        self.runtime = runtime
        self.token = os.environ.get("BACKLOT_AGENT_TOKEN", "")


class TaskHandler(BaseHTTPRequestHandler):
    server: TaskServer

    def log_message(self, format, *args):  # noqa: A002 - silence default logging
        return

    def _send(self, code: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        if not self.server.token:
            return True
        return self.headers.get("Authorization") == f"Bearer {self.server.token}"

    def do_GET(self):
        if self.path != "/health":
            self._send(404, {"ok": False, "error": "not found"})
            return
        else:
            self._send(200, self.server.runtime.health())

    def do_POST(self):
        if self.path != "/v1/task":
            self._send(404, {"ok": False, "error": "not found"})
            return
        if not self._authorized():
            self._send(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 10 * 1024 * 1024:
                raise ValueError("request size is invalid")
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            result = self.server.runtime.dispatch(request)
            self._send(200 if result.get("ok", True) else 422, result)
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"ok": False, "status": "ERROR", "error": f"invalid request ({type(exc).__name__})"})


def serve_http(runtime: Runtime | None = None, host="127.0.0.1", port=8801, workers=4):
    runtime = runtime or Runtime(workers=workers)
    server = TaskServer((host, port), runtime)
    print(json.dumps({"status": "ready", "url": f"http://{host}:{server.server_port}"}))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
