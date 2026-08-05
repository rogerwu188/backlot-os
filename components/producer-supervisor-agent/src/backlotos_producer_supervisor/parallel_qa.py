"""Parallel QA fan-out with a deterministic aggregate barrier."""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Callable

from .pipeline_gates import run_gate

MIN_WORKERS = 2
MAX_WORKERS = 32


def _run_one(task: dict, gate_runner: Callable[[str, dict], dict]) -> dict:
    started = time.monotonic()
    try:
        result = gate_runner(task["gate"], task.get("payload", {}))
        if not isinstance(result, dict):
            result = {"ok": False, "status": "ERROR", "error": "gate returned a non-object result"}
    except Exception as exc:  # noqa: BLE001 - one gate must not cancel siblings
        result = {"ok": False, "status": "ERROR", "error": f"gate raised {type(exc).__name__}"}
    return {
        "qa_id": task["qa_id"],
        "gate": task["gate"],
        "required": task.get("required", True) is not False,
        "ok": bool(result.get("ok", False)),
        "status": result.get("status", "PASS" if result.get("ok") else "FAIL"),
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "result": result,
    }


def run_parallel_qa(
    tasks: list[dict],
    workers: int = 4,
    *,
    gate_runner: Callable[[str, dict], dict] = run_gate,
) -> dict:
    """Run independent QA gates concurrently and aggregate at one barrier."""
    if not isinstance(tasks, list) or not tasks:
        return {"ok": False, "status": "ERROR", "error": "tasks must be a non-empty list"}

    normalized: list[dict] = []
    seen: set[str] = set()
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            return {"ok": False, "status": "ERROR", "error": f"tasks[{index}] must be an object"}
        qa_id = str(task.get("qa_id", "")).strip()
        gate = str(task.get("gate", "")).strip()
        if not qa_id or not gate:
            return {"ok": False, "status": "ERROR", "error": f"tasks[{index}] requires qa_id and gate"}
        if qa_id in seen:
            return {"ok": False, "status": "ERROR", "error": f"duplicate qa_id: {qa_id}"}
        seen.add(qa_id)
        normalized.append({**task, "qa_id": qa_id, "gate": gate})

    worker_count = min(max(MIN_WORKERS, min(MAX_WORKERS, int(workers))), len(normalized))
    results: list[dict | None] = [None] * len(normalized)
    started = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="backlotos-qa") as executor:
        futures = {executor.submit(_run_one, task, gate_runner): index for index, task in enumerate(normalized)}
        for future in cf.as_completed(futures):
            results[futures[future]] = future.result()

    completed = [result for result in results if result is not None]
    required_failures = [result for result in completed if result["required"] and not result["ok"]]
    advisory_failures = [result for result in completed if not result["required"] and not result["ok"]]
    ok = not required_failures
    return {
        "ok": ok,
        "status": "PASS" if ok and not advisory_failures else ("PASS_WITH_ADVISORIES" if ok else "FAIL"),
        "execution_mode": "parallel_fan_out_aggregate_barrier",
        "workers": worker_count,
        "total": len(completed),
        "passed": sum(1 for result in completed if result["ok"]),
        "failed": sum(1 for result in completed if not result["ok"]),
        "required_failures": required_failures,
        "advisory_failures": advisory_failures,
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "results": completed,
    }


def write_receipt_atomic(path: str | os.PathLike[str], receipt: dict) -> Path:
    """Persist a completed aggregate receipt without exposing partial JSON."""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(receipt, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return destination
