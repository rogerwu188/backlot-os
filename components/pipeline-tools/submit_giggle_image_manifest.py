#!/usr/bin/env python3
"""Submit a batch of Giggle image tasks concurrently with gate evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from giggle_api_client import _image_list, _request
    from giggle_credit_statements import fetch_pay_statements, reconcile_rows
    from shot_space_camera_constraint_gate import evaluate_task as evaluate_spatial_task
except ModuleNotFoundError:  # Imported as tools.submit_giggle_image_manifest.
    from tools.giggle_api_client import _image_list, _request
    from tools.giggle_credit_statements import fetch_pay_statements, reconcile_rows
    from tools.shot_space_camera_constraint_gate import evaluate_task as evaluate_spatial_task


ROOT = Path(__file__).resolve().parents[1]


def resolve(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def validate_gate(path: str) -> dict[str, Any]:
    report_path = resolve(path)
    if not report_path.is_file():
        raise ValueError(f"Missing gate report: {path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        raise ValueError(f"Gate is not PASS: {path}")
    return {"path": path, "status": "PASS", "schema": report.get("schema")}


def validate_anchor_count_gate_requirement(
    manifest: dict[str, Any], gates: list[dict[str, Any]]
) -> None:
    tasks = manifest.get("tasks") or []
    if not any(task.get("video_unit_id") for task in tasks):
        return
    if not any(gate.get("schema") == "qingshan.video_unit_anchor_count_gate.v1" for gate in gates):
        raise ValueError(
            "Video-unit image batches require a passing qingshan.video_unit_anchor_count_gate.v1 report; "
            "anchor count must be justified per unit, never fixed to one or fixed to multiple images."
        )

    consumer = manifest.get("consumer_contract") or {}
    planned = consumer.get("planned_anchor_count")
    if not isinstance(planned, int) or planned <= len(tasks):
        return
    dependent = manifest.get("dependent_anchor_specs") or []
    if len(dependent) != planned - len(tasks):
        raise ValueError(
            "Partial anchor batches must declare every dependent anchor before initial submit"
        )
    initial_keys = {task.get("task_key") for task in tasks}
    dependent_keys = {row.get("task_key") for row in dependent}
    if None in dependent_keys or len(dependent_keys) != len(dependent):
        raise ValueError("Dependent anchor task keys must be present and unique")
    if any(row.get("depends_on_task_key") not in initial_keys for row in dependent):
        raise ValueError("Every dependent anchor must name an initial task dependency")
    if set(manifest.get("blocked_tasks") or []) != dependent_keys:
        raise ValueError("blocked_tasks must exactly match declared dependent anchors")


def validate_task(task: dict[str, Any]) -> None:
    for field in ("task_key", "prompt_file", "reference_images"):
        if not task.get(field):
            raise ValueError(f"{task.get('task_key', 'UNKNOWN')} missing {field}")
    if task.get("tool_type") != "image_generation":
        raise ValueError(f"{task['task_key']} is not an image_generation task")
    prompt_path = resolve(task["prompt_file"])
    if not prompt_path.is_file():
        raise ValueError(f"Missing prompt: {task['prompt_file']}")
    actual_prompt_sha = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    if actual_prompt_sha != task.get("prompt_sha256"):
        raise ValueError(f"{task['task_key']} prompt SHA mismatch")
    contract = task.get("prompt_contract") or {}
    if contract.get("schema") != "qingshan.image_prompt_contract.v2" or contract.get("status") != "PASS":
        raise ValueError(f"{task['task_key']} prompt contract is not PASS v2")
    if contract.get("shot_id") != task.get("shot_id") or contract.get("source_script_sha256") != task.get("source_script_sha256"):
        raise ValueError(f"{task['task_key']} prompt contract source binding mismatch")
    if contract.get("source_action_sha256") != hashlib.sha256(str(contract.get("source_action", "")).encode("utf-8")).hexdigest():
        raise ValueError(f"{task['task_key']} source action SHA mismatch")
    prompt_text = prompt_path.read_text(encoding="utf-8")
    if contract.get("source_action") not in prompt_text:
        raise ValueError(f"{task['task_key']} prompt omits exact source action")
    spatial = evaluate_spatial_task(task, prompt_text)
    if spatial["status"] != "PASS":
        codes = ", ".join(row["code"] for row in spatial["failures"])
        raise ValueError(f"{task['task_key']} spatial/camera gate failed: {codes}")
    bindings = task.get("reference_bindings") or []
    if bindings != contract.get("reference_bindings"):
        raise ValueError(f"{task['task_key']} reference bindings differ from prompt contract")
    character_ids = [row.get("entity_id") for row in bindings if row.get("role") == "character"]
    if character_ids != contract.get("visible_characters"):
        raise ValueError(f"{task['task_key']} visible-character/reference mismatch")
    if any(row.get("qa_status") != "PASS" for row in bindings if row.get("role") == "character"):
        raise ValueError(f"{task['task_key']} has an unverified character identity asset")
    if len([row for row in bindings if row.get("role") in {"scene", "destination_scene"}]) != 1:
        raise ValueError(f"{task['task_key']} must have exactly one scene reference")
    for binding in bindings:
        path = resolve(binding["path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != binding.get("sha256"):
            raise ValueError(f"{task['task_key']} reference binding SHA mismatch: {binding.get('path')}")
    if task.get("reference_images") != [row["path"] for row in bindings]:
        raise ValueError(f"{task['task_key']} reference image order differs from bound contract")


def submit_one(task: dict[str, Any], receipt_dir: Path) -> dict[str, Any]:
    prompt = resolve(task["prompt_file"]).read_text(encoding="utf-8")
    references = [str(resolve(path)) for path in task["reference_images"]]
    payload = {
        "prompt": prompt,
        "reference_images": _image_list(references),
        "generate_count": 1,
        "model": task.get("model", "gpt-image-2-pro"),
        "aspect_ratio": task.get("aspect_ratio", "9:16"),
        "resolution": task.get("resolution", "1K"),
        "watermark": False,
    }
    response = _request("/api/v1/generation/image-to-image", payload)
    task_id = (response.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError("Submit response missing data.task_id")
    receipt = receipt_dir / f"{task['task_key']}_submit_receipt.json"
    receipt.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "task_key": task["task_key"],
        "beat_id": task.get("beat_id"),
        "task_id": task_id,
        "status": "submitted",
        "receipt": str(receipt.relative_to(ROOT)),
    }


def submit_all(
    tasks: list[dict[str, Any]], receipt_dir: Path, concurrency: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Submit every item and preserve isolated client exits as item failures."""
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(submit_one, task, receipt_dir): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                results.append(future.result())
            except (Exception, SystemExit) as exc:
                failures.append({
                    "task_key": task["task_key"],
                    "status": "submit_failed",
                    "credit": 0,
                    "credit_status": "FAILED_ZERO",
                    "error": str(exc),
                })
    return results, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--precheck-only", action="store_true")
    parser.add_argument("--task-key", action="append", default=[], help="Submit only the named task key; repeat as needed")
    args = parser.parse_args()

    manifest_path = resolve(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    all_tasks = manifest.get("tasks") or []
    if not all_tasks:
        raise SystemExit("Image manifest contains zero tasks")
    gates = [validate_gate(path) for path in manifest.get("machine_gate_reports") or []]
    if not gates:
        raise SystemExit("Image manifest has no machine_gate_reports")
    validate_anchor_count_gate_requirement(manifest, gates)
    tasks = all_tasks
    if args.task_key:
        requested = set(args.task_key)
        available = {task.get("task_key") for task in all_tasks}
        unknown = sorted(requested - available)
        if unknown:
            raise SystemExit(f"Unknown image task keys: {', '.join(unknown)}")
        tasks = [task for task in all_tasks if task.get("task_key") in requested]
    for task in tasks:
        validate_task(task)
    if not args.precheck_only and not os.environ.get("GIGGLE_API_KEY", "").strip():
        raise SystemExit("GIGGLE_API_KEY is not set")

    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    receipt_dir = out.parent / f"{out.stem}_receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    submit_started_at = datetime.now(timezone.utc)
    if args.precheck_only:
        results = [{"task_key": task["task_key"], "beat_id": task.get("beat_id"), "status": "precheck_pass"} for task in tasks]
    else:
        results, failures = submit_all(tasks, receipt_dir, args.concurrency)
    submit_finished_at = datetime.now(timezone.utc)

    results.sort(key=lambda row: row["task_key"])
    failures.sort(key=lambda row: row["task_key"])
    credit_reconciliation = None
    if not args.precheck_only and results:
        expected_credit_count = sum(row["status"] == "submitted" for row in results)
        for attempt in range(7):
            credit_reconciliation = reconcile_rows(
                fetch_pay_statements(),
                start=submit_started_at - timedelta(seconds=10),
                end=datetime.now(timezone.utc) + timedelta(seconds=10),
                expected_count=expected_credit_count,
                event_description="SingleGenerateImage",
                model=str(tasks[0].get("model", "gpt-image-2-pro")),
            )
            if credit_reconciliation["status"] == "PASS" or attempt == 6:
                break
            time.sleep(5)
        credit_out = out.parent / f"{out.stem}_credit_statement.json"
        credit_out.write_text(json.dumps(credit_reconciliation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    generation_pass = len(results) == len(tasks) and not failures
    cost_pass = args.precheck_only or (credit_reconciliation or {}).get("status") == "PASS"
    report = {
        "schema": "qingshan.giggle_image_batch_submit.v1",
        "episode": manifest.get("episode"),
        "manifest": str(manifest_path.relative_to(ROOT)),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "precheck_only": args.precheck_only,
        "concurrency": max(1, args.concurrency),
        "task_filter": sorted(args.task_key),
        "machine_gates": gates,
        "status": "PASS" if generation_pass and cost_pass else "FAIL",
        "submitted": sum(row["status"] == "submitted" for row in results),
        "precheck_pass": sum(row["status"] == "precheck_pass" for row in results),
        "failed": len(failures),
        "results": results,
        "failures": failures,
        "credit_reconciliation": credit_reconciliation,
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "submitted", "precheck_pass", "failed")}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
