#!/usr/bin/env python3
"""Fail-closed gate executed by the real paid video submission entrypoint."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from performance_tempo_gate import evaluate_batch as evaluate_performance_tempo
from provider_video_capability_gate import evaluate_provider_capability
from exact_first_frame_transport import evaluate_batch as evaluate_exact_first_frame_transport


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


def _combat_causality_failures(tasks: list[dict[str, Any]], tempo: dict[str, Any]) -> list[dict[str, Any]]:
    """Reject combat that has motion timing but no viewer-readable cause and effect."""
    fight_keys = {row["task_key"] for row in tempo.get("rows") or [] if row.get("fight_or_chase")}
    failures: list[dict[str, Any]] = []
    for task in tasks:
        key = str(task.get("task_key") or "UNKNOWN")
        if key not in fight_keys:
            continue
        contract = task.get("combat_choreography_contract")
        if not isinstance(contract, dict):
            failures.append({"code": "COMBAT_CHOREOGRAPHY_CONTRACT_MISSING", "task_key": key})
            continue
        for field in ("initiator", "objective", "spatial_axis", "terminal_state"):
            if not contract.get(field):
                failures.append({"code": "COMBAT_CHOREOGRAPHY_FIELD_MISSING", "task_key": key, "field": field})
        beats = contract.get("causal_beats")
        if not isinstance(beats, list) or not beats:
            failures.append({"code": "COMBAT_CAUSAL_BEATS_MISSING", "task_key": key})
            continue
        for index, beat in enumerate(beats, 1):
            missing = [field for field in ("attack_intent", "defense_response", "visible_consequence", "end_state") if not isinstance(beat, dict) or not beat.get(field)]
            if missing:
                failures.append({"code": "COMBAT_CAUSAL_BEAT_INCOMPLETE", "task_key": key, "index": index, "missing": missing})
        terminal = contract.get("terminal_state")
        if isinstance(terminal, dict):
            missing = [field for field in ("winner", "loser", "physical_result") if not terminal.get(field)]
            if missing:
                failures.append({"code": "COMBAT_TERMINAL_STATE_INCOMPLETE", "task_key": key, "missing": missing})
        else:
            failures.append({"code": "COMBAT_TERMINAL_STATE_INCOMPLETE", "task_key": key})
    return failures


def evaluate_manifest(
    manifest: dict[str, Any],
    *,
    root: str | Path,
    manifest_path: str | Path | None = None,
    capability_registry_path: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate the current manifest itself; historical PASS receipts cannot substitute."""
    root_path = Path(root).resolve()
    tasks, failures = _hydrated_tasks(manifest, root_path)
    if not tasks:
        failures.append({"code": "CURRENT_MANIFEST_TASKS_MISSING"})
    tempo = evaluate_performance_tempo(tasks)
    provider_capability = evaluate_provider_capability(
        manifest,
        tasks,
        registry_path=capability_registry_path,
    )
    exact_first_frame_transport = evaluate_exact_first_frame_transport(tasks, root=root_path)
    failures.extend(provider_capability.get("failures") or [])
    failures.extend(exact_first_frame_transport.get("failures") or [])
    failures.extend(tempo.get("failures") or [])
    failures.extend(_combat_causality_failures(tasks, tempo))

    manifest_sha = None
    if manifest_path is not None:
        path = _resolve(root_path, manifest_path)
        if not path.is_file():
            failures.append({"code": "CURRENT_MANIFEST_FILE_MISSING", "path": str(manifest_path)})
        else:
            manifest_sha = _sha256_bytes(path.read_bytes())

    gate_path = Path(__file__).resolve()
    tempo_path = Path(__file__).with_name("performance_tempo_gate.py").resolve()
    provider_gate_path = Path(__file__).with_name("provider_video_capability_gate.py").resolve()
    exact_transport_path = Path(__file__).with_name("exact_first_frame_transport.py").resolve()
    provider_registry_path = Path(
        capability_registry_path
        or Path(__file__).with_name("provider_video_capabilities.json")
    ).resolve()
    return {
        "schema": "backlotos.production_video_submission_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "manifest_sha256": manifest_sha,
        "task_contract_sha256": _sha256_bytes(_canonical_json(manifest.get("tasks") or [])),
        "task_keys": [str(task.get("task_key") or "UNKNOWN") for task in tasks],
        "performance_tempo": tempo,
        "provider_capability": provider_capability,
        "exact_first_frame_transport": exact_first_frame_transport,
        "failures": failures,
        "runtime_binding": {
            "gate_path": str(gate_path),
            "gate_sha256": _sha256_bytes(gate_path.read_bytes()),
            "performance_tempo_gate_path": str(tempo_path),
            "performance_tempo_gate_sha256": _sha256_bytes(tempo_path.read_bytes()),
            "provider_video_capability_gate_path": str(provider_gate_path),
            "provider_video_capability_gate_sha256": _sha256_bytes(provider_gate_path.read_bytes()),
            "exact_first_frame_transport_path": str(exact_transport_path),
            "exact_first_frame_transport_sha256": _sha256_bytes(exact_transport_path.read_bytes()),
            "provider_video_capabilities_path": str(provider_registry_path),
            "provider_video_capabilities_sha256": (
                _sha256_bytes(provider_registry_path.read_bytes()) if provider_registry_path.is_file() else None
            ),
        },
        "policy": "The paid submit entrypoint must evaluate this exact manifest fail-closed; historical gate reports are supplementary only. Seedance 2 video submissions require seedance-2.0-fast at provider-native 720p. EXACT_FIRST_FRAME tasks must use image-to-video start_frame, never Omni images[], and harvested output must pass frame0 authority plus frame0-to-frame1 continuity without automatic prepend or replacement. Combat requires a viewer-readable attack-response-consequence chain, stable spatial axis, and explicit winner/loser terminal state.",
    }
