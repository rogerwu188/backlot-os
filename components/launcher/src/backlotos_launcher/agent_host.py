from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .pipeline import credit_summary, record_credit, status

ROLES = {"producer", "story", "pipeline", "post", "review"}


class RoleDispatcher:
    def __init__(self, role: str, workers: int = 4):
        if role not in ROLES:
            raise ValueError(f"unknown role: {role}")
        self.role = role
        self.workers = max(4, int(workers))
        self._runtime = None

    def health(self) -> dict:
        base = {"ok": True, "status": "ready", "role": self.role, "workers": self.workers}
        if self.role == "story":
            from claude_story_agent.model_adapter import ModelAdapter
            model = ModelAdapter().health()
            return {**base, "model": model, "generation": "SUPPORTED" if model.get("available") else "ADAPTER_REQUIRED", "review": "SUPPORTED"}
        if self.role == "post":
            from agentcut.agent import AgentServer
            from agentcut.engine import AgentCutEngine
            result = AgentServer(AgentCutEngine(), 1).handle({"id": "health", "method": "health", "params": {}})["result"]
            return {**base, "tool": result, "status": "ready" if result.get("ready") else "dependency_unavailable"}
        if self.role == "review":
            return {**base, "review": "SUPPORTED", "release_preflight": "SUPPORTED", "platform_publish": "HUMAN_ONLY"}
        command_name = "BACKLOT_PRODUCER_COMMAND" if self.role == "producer" else "BACKLOT_PIPELINE_COMMAND"
        configured = _command_available(os.environ.get(command_name, ""))
        return {**base, "semantic_adapter": "SUPPORTED" if configured else "ADAPTER_REQUIRED", "adapter_env": command_name}

    def dispatch(self, request: dict) -> dict:
        method = request.get("method") or request.get("verb")
        params = request.get("params") or request
        if method == "health":
            return self.health()
        if self.role == "story":
            from claude_story_agent.model_adapter import ModelAdapter
            from claude_story_agent.runtime import Runtime
            self._runtime = self._runtime or Runtime(ModelAdapter(), self.workers)
            return self._runtime.dispatch({**params, "verb": method})
        if self.role == "post":
            from agentcut.agent import AgentServer
            from agentcut.engine import AgentCutEngine
            self._runtime = self._runtime or AgentServer(AgentCutEngine(), self.workers)
            return self._runtime.handle({"id": request.get("id"), "method": method, "params": request.get("params", {})})
        if self.role == "review":
            from qingshan_review.agent import Agent
            from qingshan_review.core import Reviewer
            self._runtime = self._runtime or Agent(Reviewer(workers=self.workers))
            return self._runtime.handle({"id": request.get("id"), "method": method, "params": request.get("params", {})})
        if method in {"status", "progress"} and params.get("project"):
            return {"ok": True, **status(Path(params["project"]))}
        if self.role == "pipeline" and method == "recordCredit":
            event = record_credit(
                Path(params["project"]), params["episode_id"], params["stage"],
                float(params["consumed"]), float(params.get("refunded", 0)), params.get("estimated"),
                params.get("provider", "unknown"), params.get("provider_task_id"),
                params.get("evidence_ref"), bool(params.get("final", True)),
            )
            return {"ok": True, "event": event, "summary": credit_summary(Path(params["project"]), params["episode_id"])}
        command_name = "BACKLOT_PRODUCER_COMMAND" if self.role == "producer" else "BACKLOT_PIPELINE_COMMAND"
        return _external(command_name, request)


def _command_available(command: str) -> bool:
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    return bool(argv) and bool(shutil.which(argv[0]))


def _external(command_name: str, payload: dict) -> dict:
    command = os.environ.get(command_name, "")
    if not _command_available(command):
        return {"ok": False, "status": "CAPABILITY_FAIL", "error": f"{command_name} adapter is not configured"}
    argv = shlex.split(command)
    try:
        completed = subprocess.run(argv, input=json.dumps(payload, ensure_ascii=False), text=True, capture_output=True, timeout=900, shell=False)
    except Exception as exc:
        return {"ok": False, "status": "ERROR", "error": f"adapter execution failed ({type(exc).__name__})"}
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        suffix = f" and exited with code {completed.returncode}" if completed.returncode else ""
        return {"ok": False, "status": "ERROR", "error": f"adapter returned invalid JSON{suffix}; stderr withheld"}
    if not isinstance(result, dict):
        return {"ok": False, "status": "ERROR", "error": "adapter result must be an object"}
    # Content/capability failures intentionally use a non-zero process exit
    # so generic supervisors cannot mistake them for tool success. Preserve
    # the adapter's structured result instead of replacing it with a generic
    # transport error.
    if completed.returncode:
        result = {**result, "adapter_exit_code": completed.returncode}
        result.setdefault("ok", False)
    return result


class RoleServer(ThreadingHTTPServer):
    def __init__(self, address, role: str, workers: int = 4):
        super().__init__(address, RoleHandler)
        self.dispatcher = RoleDispatcher(role, workers)
        self.token = os.environ.get("BACKLOT_AGENT_TOKEN", "")


class RoleHandler(BaseHTTPRequestHandler):
    server: RoleServer

    def log_message(self, format, *args):
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
        else:
            self._send(200, self.server.dispatcher.health())

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
            result = self.server.dispatcher.dispatch(request)
            self._send(200 if result.get("ok", True) else 422, result)
        except Exception as exc:
            self._send(400, {"ok": False, "status": "ERROR", "error": f"invalid request ({type(exc).__name__})"})


def serve_role(role: str, host="127.0.0.1", port=8801, workers=4):
    server = RoleServer((host, port), role, workers)
    print(json.dumps({"status": "ready", "role": role, "url": f"http://{host}:{server.server_port}"}))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
