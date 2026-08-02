"""Console-script entrypoints.

- backlotos-producer-command: satisfies BACKLOT_PRODUCER_COMMAND -- reads one
  JSON request from stdin, writes exactly one JSON object to stdout, and uses
  a non-zero exit when that structured result is not ok.
- backlotos-pipeline-command: satisfies BACKLOT_PIPELINE_COMMAND -- same
  protocol, dispatches to the generic pipeline-tools gate wrappers.
- backlotos-producer-agent: standalone single-shot CLI / NDJSON serve / HTTP
  serve entrypoint (same pattern as claude-story-agent's CLI), for running
  this package directly outside the launcher's external-command proxy.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .http_server import serve_http
from .invoker import AgentInvoker
from .pipeline_gates import health as pipeline_health
from .pipeline_gates import run_edit_plan_integrity, run_gate
from .runtime import Runtime


def _read_one_request(argv_infile: str | None) -> dict:
    if argv_infile:
        with open(argv_infile, encoding="utf-8") as stream:
            return json.load(stream)
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def _print_one(result: dict) -> int:
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0 if result.get("ok", False) else 1


def producer_command_main(argv=None) -> int:
    """Entrypoint for BACKLOT_PRODUCER_COMMAND: one JSON request on stdin -> one JSON object on stdout."""
    ap = argparse.ArgumentParser(prog="backlotos-producer-command")
    ap.add_argument("--in", dest="infile", default=None)
    args = ap.parse_args(argv)
    try:
        request = _read_one_request(args.infile)
    except (OSError, json.JSONDecodeError) as exc:
        return _print_one({"ok": False, "status": "ERROR", "error": f"invalid input ({type(exc).__name__})"})
    workers = int(os.environ.get("BACKLOT_PRODUCER_WORKERS", "4"))
    runtime = Runtime(AgentInvoker(), workers=workers)
    try:
        result = runtime.dispatch(request)
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "status": "ERROR", "error": f"request failed ({type(exc).__name__})"}
    return _print_one(result)


def pipeline_command_main(argv=None) -> int:
    """Entrypoint for BACKLOT_PIPELINE_COMMAND: one JSON request on stdin -> one JSON object on stdout."""
    ap = argparse.ArgumentParser(prog="backlotos-pipeline-command")
    ap.add_argument("--in", dest="infile", default=None)
    args = ap.parse_args(argv)
    try:
        request = _read_one_request(args.infile)
    except (OSError, json.JSONDecodeError) as exc:
        return _print_one({"ok": False, "status": "ERROR", "error": f"invalid input ({type(exc).__name__})"})
    method = request.get("method") or request.get("verb")
    params = request.get("params") or {}
    try:
        if method == "health":
            result = pipeline_health()
        elif method == "gate":
            gate_name = params.get("gate")
            payload = params.get("payload", {})
            result = run_gate(gate_name, payload)
        elif method == "edit-plan-integrity":
            result = run_edit_plan_integrity(params.get("rows", []), params.get("target_fps", 30.0), params.get("tolerance", 0.05))
        else:
            result = {"ok": False, "status": "ERROR", "error": f"unknown method: {method}", "known_methods": ["health", "gate", "edit-plan-integrity"]}
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "status": "ERROR", "error": f"request failed ({type(exc).__name__})"}
    return _print_one(result)


def producer_agent_main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="backlotos-producer-agent")
    ap.add_argument("verb", choices=["health", "validate", "plan", "dispatch", "dispatchMany", "supervise", "status", "progress", "resume", "retry-failed", "cost-summary", "review-decision", "serve", "serve-http"])
    ap.add_argument("--in", dest="infile", default=None)
    ap.add_argument("--workers", type=int, default=int(os.environ.get("BACKLOT_PRODUCER_WORKERS", "4")))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8801)
    args = ap.parse_args(argv)
    runtime = Runtime(AgentInvoker(), workers=args.workers)
    if args.verb == "serve":
        runtime.serve_ndjson()
        return 0
    if args.verb == "serve-http":
        serve_http(runtime, host=args.host, port=args.port, workers=args.workers)
        return 0
    try:
        if args.infile:
            with open(args.infile, encoding="utf-8") as stream:
                req = json.load(stream)
        elif args.verb in {"health", "status", "progress"} and sys.stdin.isatty():
            req = {}
        elif not sys.stdin.isatty():
            req = json.load(sys.stdin)
        else:
            req = {}
    except (OSError, json.JSONDecodeError) as exc:
        return _print_one({"ok": False, "status": "ERROR", "error": f"invalid input ({type(exc).__name__})"})
    req["verb"] = args.verb
    try:
        result = runtime.dispatch(req)
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "status": "ERROR", "error": f"request failed ({type(exc).__name__})"}
    return _print_one(result)


if __name__ == "__main__":
    raise SystemExit(producer_agent_main())
