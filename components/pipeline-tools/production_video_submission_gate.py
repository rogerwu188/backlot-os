#!/usr/bin/env python3
"""Fail-closed gate executed by the real paid video submission entrypoint."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from performance_tempo_gate import evaluate_batch as evaluate_performance_tempo


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _hydrated_tasks(manifest: dict[str, Any], root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tasks: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for original in manifest.get("tasks") or []:
        task = dict(original)
        if task.get("model") != "seedance-2.0":
            failures.append({
                "code": "STANDARD_SEEDANCE2_MODEL_REQUIRED",
                "task_key": task.get("task_key"),
                "actual_model": task.get("model"),
                "required_model": "seedance-2.0",
            })
        prompt_file = task.get("prompt_file")
        if prompt_file:
            prompt_path = _resolve(root, str(prompt_file))
            if not prompt_path.is_file():
                failures.append({"code": "CURRENT_PROMPT_FILE_MISSING", "task_key": task.get("task_key"), "path": str(prompt_file)})
            else:
                actual = _sha256_bytes(prompt_path.read_bytes())
                if actual != task.get("prompt_sha256"):
                    failures.append({"code": "CURRENT_PROMPT_SHA_MISMATCH", "task_key": task.get("task_key"), "actual": actual, "expected": task.get("prompt_sha256")})
                task["prompt_text"] = prompt_path.read_text(encoding="utf-8", errors="ignore")
        tasks.append(task)
    return tasks, failures


def evaluate_manifest(manifest: dict[str, Any], *, root: str | Path, manifest_path: str | Path | None = None) -> dict[str, Any]:
    """Evaluate the current manifest itself; historical PASS receipts cannot substitute."""
    root_path = Path(root).resolve()
    tasks, failures = _hydrated_tasks(manifest, root_path)
    if not tasks:
        failures.append({"code": "CURRENT_MANIFEST_TASKS_MISSING"})
    tempo = evaluate_performance_tempo(tasks)
    failures.extend(tempo.get("failures") or [])

    manifest_sha = None
    if manifest_path is not None:
        path = _resolve(root_path, manifest_path)
        if not path.is_file():
            failures.append({"code": "CURRENT_MANIFEST_FILE_MISSING", "path": str(manifest_path)})
        else:
            manifest_sha = _sha256_bytes(path.read_bytes())

    gate_path = Path(__file__).resolve()
    tempo_path = Path(__file__).with_name("performance_tempo_gate.py").resolve()
    return {
        "schema": "backlotos.production_video_submission_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "manifest_sha256": manifest_sha,
        "task_contract_sha256": _sha256_bytes(_canonical_json(manifest.get("tasks") or [])),
        "task_keys": [str(task.get("task_key") or "UNKNOWN") for task in tasks],
        "performance_tempo": tempo,
        "failures": failures,
        "runtime_binding": {
            "gate_path": str(gate_path),
            "gate_sha256": _sha256_bytes(gate_path.read_bytes()),
            "performance_tempo_gate_path": str(tempo_path),
            "performance_tempo_gate_sha256": _sha256_bytes(tempo_path.read_bytes()),
        },
        "policy": "The paid submit entrypoint must evaluate this exact manifest fail-closed; historical gate reports are supplementary only. Seedance 2 video submissions require the standard seedance-2.0 model; Pro is forbidden.",
    }
