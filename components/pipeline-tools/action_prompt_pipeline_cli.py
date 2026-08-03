#!/usr/bin/env python3
"""Compile and validate an ordered action-prompt manifest before generation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from action_actor_ownership_gate import evaluate_batch as actor_ownership_gate
from action_direction_contract_gate import evaluate_batch as direction_gate
from action_sequence_continuity_gate import evaluate_batch as continuity_gate
from action_spatial_feasibility_gate import evaluate_batch as spatial_gate
from generation_prompt_optimizer import optimize_prompt, validate_batch as optimizer_gate


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_prompt(task: dict[str, Any], manifest_dir: Path) -> str:
    if isinstance(task.get("prompt"), str):
        return task["prompt"]
    prompt_file = task.get("prompt_file")
    if not prompt_file:
        raise ValueError(f"{task.get('task_key', 'unknown')}: prompt or prompt_file is required")
    return (manifest_dir / str(prompt_file)).resolve().read_text(encoding="utf-8")


def compile_manifest(manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tasks = manifest.get("tasks") or []
    if not tasks:
        raise ValueError("manifest.tasks must contain at least one ordered action task")
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_dir = output_dir / "prompts"
    prompt_dir.mkdir(exist_ok=True)
    prompts: dict[str, str] = {}
    compiled_tasks: list[dict[str, Any]] = []

    for index, source_task in enumerate(tasks, start=1):
        task = dict(source_task)
        key = str(task.get("task_key") or f"ACTION-{index:03d}")
        task["task_key"] = key
        task["prompt_optimizer_required"] = True
        optimized, receipt = optimize_prompt(task, _read_prompt(task, manifest_path.parent), compiled_tasks)
        prompt_path = prompt_dir / f"{index:03d}_{key.replace('/', '_')}.txt"
        prompt_path.write_text(optimized, encoding="utf-8")
        task.pop("prompt", None)
        task["prompt_file"] = str(prompt_path.relative_to(output_dir))
        task["prompt_sha256"] = _sha_text(optimized)
        task["prompt_optimizer_receipt"] = receipt
        prompts[key] = optimized
        compiled_tasks.append(task)

    gates = {
        "prompt_optimizer": optimizer_gate(compiled_tasks, prompts),
        "spatial_feasibility": spatial_gate(compiled_tasks, prompts),
        "sequence_continuity": continuity_gate(compiled_tasks),
        "direction": direction_gate(compiled_tasks),
        "actor_ownership": actor_ownership_gate(compiled_tasks, prompts),
    }
    status = "PASS" if all(row.get("status") == "PASS" for row in gates.values()) else "FAIL"
    compiled = {
        "schema": "backlotos.action-prompt-batch/1.0",
        "status": status,
        "source_manifest": str(manifest_path),
        "tasks": compiled_tasks,
    }
    report = {
        "schema": "backlotos.action-prompt-pre-submit-report/1.0",
        "status": status,
        "task_count": len(compiled_tasks),
        "gates": gates,
    }
    (output_dir / "compiled_manifest.json").write_text(json.dumps(compiled, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "pre_submit_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = compile_manifest(args.manifest.resolve(), args.output_dir.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
