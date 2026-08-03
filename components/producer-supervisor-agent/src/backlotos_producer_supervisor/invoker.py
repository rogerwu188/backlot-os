"""Pluggable downstream-agent invocation layer.

Hard rules (same posture as claude_story_agent.model_adapter):
  * NEVER fabricate a PASS/COMPLETED result when no backend is reachable.
  * If the target agent cannot be reached, raise CapabilityError; callers
    must turn that into a BLOCKED job with reason ADAPTER_REQUIRED /
    CAPABILITY_FAIL -- never a fabricated success.
  * NEVER write, log, or return a real secret/token value.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any, Callable


class CapabilityError(RuntimeError):
    """Raised when a downstream agent cannot be reached to execute a job."""


class AgentInvoker:
    """Backend-agnostic caller: http | command | mock.

    Configuration is per target-agent-name via environment variables of the
    form ``BACKLOT_AGENT_<NAME>_URL`` (http backend) or
    ``BACKLOT_AGENT_<NAME>_COMMAND`` (command backend, argv split with
    shlex, executed without a shell -- mirrors backlotos_launcher.agent_host
    ``_external()``).
    """

    def __init__(self, mode: str | None = None, mock_fn: Callable[[str, dict], dict] | None = None, timeout: float = 60.0):
        self.mode = mode or os.environ.get("BACKLOT_INVOKER_MODE", "auto")
        self._mock_fn = mock_fn
        self.timeout = timeout
        self.calls: list[tuple[str, dict]] = []  # observability for tests: every attempted call

    def set_mock(self, fn: Callable[[str, dict], dict]) -> None:
        self._mock_fn = fn
        self.mode = "mock"

    def _resolve_backend(self, agent_name: str) -> tuple[str, str] | None:
        env_prefix = agent_name.upper().replace("-", "_")
        command = os.environ.get(f"BACKLOT_AGENT_{env_prefix}_COMMAND", "")
        url = os.environ.get(f"BACKLOT_AGENT_{env_prefix}_URL", "")
        if self.mode in ("command",) or (self.mode == "auto" and command):
            if command:
                return "command", command
        if self.mode in ("http",) or (self.mode == "auto" and url):
            if url:
                return "http", url
        return None

    def health(self, agent_name: str) -> dict:
        if self.mode == "mock" or self._mock_fn is not None:
            return {"mode": "mock", "available": True, "agent": agent_name}
        resolved = self._resolve_backend(agent_name)
        if resolved is None:
            return {"mode": "unavailable", "available": False, "agent": agent_name}
        backend, target = resolved
        if backend == "command":
            try:
                argv = shlex.split(target)
            except ValueError:
                argv = []
            ok = bool(argv) and bool(shutil.which(argv[0]))
            return {"mode": "command", "available": ok, "agent": agent_name}
        return {"mode": "http", "available": True, "agent": agent_name, "note": "reachability not probed until dispatch"}

    def invoke(self, agent_name: str, payload: dict) -> dict:
        """Invoke the given downstream agent with payload; return its raw dict result.

        Raises CapabilityError if no backend is configured/reachable. Never
        returns a fabricated success.
        """
        self.calls.append((agent_name, payload))
        if self._mock_fn is not None or self.mode == "mock":
            if self._mock_fn is None:
                raise CapabilityError(f"mock mode selected for {agent_name} but no mock function registered")
            return self._mock_fn(agent_name, payload)

        resolved = self._resolve_backend(agent_name)
        if resolved is None:
            raise CapabilityError(f"no invoker backend configured for agent '{agent_name}' (set BACKLOT_AGENT_{agent_name.upper()}_COMMAND or _URL)")
        backend, target = resolved
        if backend == "command":
            try:
                argv = shlex.split(target)
            except ValueError as exc:
                raise CapabilityError(f"invalid command for agent '{agent_name}': {exc}") from exc
            if not argv or not shutil.which(argv[0]):
                raise CapabilityError(f"command for agent '{agent_name}' is not executable on PATH")
            try:
                completed = subprocess.run(
                    argv, input=json.dumps(payload, ensure_ascii=False), text=True,
                    capture_output=True, timeout=self.timeout, shell=False,
                )
            except Exception as exc:  # noqa: BLE001 - convert every failure to CapabilityError
                raise CapabilityError(f"command invocation failed for '{agent_name}' ({type(exc).__name__})") from exc
            if completed.returncode:
                raise CapabilityError(f"agent '{agent_name}' command exited {completed.returncode}")
            try:
                result = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                raise CapabilityError(f"agent '{agent_name}' returned invalid JSON") from exc
            if not isinstance(result, dict):
                raise CapabilityError(f"agent '{agent_name}' result must be a JSON object")
            return result

        # http backend
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(target, data=data, headers={"Content-Type": "application/json"}, method="POST")
        token = os.environ.get("BACKLOT_AGENT_TOKEN", "")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                body = resp.read()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise CapabilityError(f"http invocation failed for agent '{agent_name}' ({type(exc).__name__})") from exc
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise CapabilityError(f"agent '{agent_name}' returned invalid JSON over http") from exc
        if not isinstance(result, dict):
            raise CapabilityError(f"agent '{agent_name}' http result must be a JSON object")
        return result
