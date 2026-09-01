#!/usr/bin/env python3
"""Durable episode-policy Giggle video submitter with exact-frame transport."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from exact_first_frame_transport import build_provider_request, raw_rgb_sha256, transport_fingerprint
    from giggle_api_client import _b64, _request, paid_video_submission_context
    from giggle_credit_statements import fetch_pay_statements, reconcile_rows
except ModuleNotFoundError:
    from tools.exact_first_frame_transport import build_provider_request, raw_rgb_sha256, transport_fingerprint
    from tools.giggle_api_client import _b64, _request, paid_video_submission_context
    from tools.giggle_credit_statements import fetch_pay_statements, reconcile_rows


ROOT = Path.cwd().resolve()
PIPELINE_TOOLS = Path(__file__).resolve().parent


def configure_project_root(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Project root is not an existing directory: {value}")
    return path


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def portable(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run_authoritative_submission_gate(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    module_path = PIPELINE_TOOLS / "production_video_submission_gate.py"
    spec = importlib.util.spec_from_file_location("backlotos_production_video_submission_gate", module_path)
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load authoritative production video submission gate")
    sys.path.insert(0, str(PIPELINE_TOOLS))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = module.evaluate_manifest(manifest, root=ROOT, manifest_path=manifest_path)
    finally:
        if sys.path and sys.path[0] == str(PIPELINE_TOOLS):
            sys.path.pop(0)
    if report.get("status") != "PASS":
        codes = sorted({str(row.get("code") or "UNKNOWN") for row in report.get("failures") or []})
        raise ValueError(f"Authoritative production video gate failed: {','.join(codes)}")
    return report


def normalized_han(value: str) -> str:
    return re.sub(r"[^\u3400-\u9fffA-Za-z0-9]", "", value or "")


def validate_source_caption_safe_dialogue(task: dict[str, Any], prompt_text: str) -> None:
    if task.get("native_dialogue_required") is not True or task.get("source_subtitle_policy", "FORBID") != "FORBID":
        return
    lines = [str(value) for value in task.get("dialogue_lines") or []]
    if task.get("dialogue_transport") == "MODEL_NATIVE_TEXT_DIALOGUE":
        if task.get("model_native_text_dialogue") is not True or not lines:
            raise ValueError(f"{task['task_key']} native text dialogue contract is incomplete")
        prompt = normalized_han(prompt_text)
        if any(normalized_han(line) not in prompt for line in lines):
            raise ValueError(f"{task['task_key']} canonical native text dialogue is missing from prompt")
        return
    if task.get("dialogue_transport") != "EXACT_LINE_AUDIO_REFERENCE":
        raise ValueError(f"{task['task_key']} source-caption-forbidden dialogue requires exact-line audio")
    exact_assets = task.get("exact_dialogue_audio_asset_ids") or []
    if not lines or len(exact_assets) != len(lines):
        raise ValueError(f"{task['task_key']} requires one ordered exact-line audio asset per line")
    prompt = normalized_han(prompt_text)
    if any(normalized_han(line) and normalized_han(line) in prompt for line in lines):
        raise ValueError(f"{task['task_key']} literal dialogue leaked into visual prompt")


def run_project_prompt_lineage_gate(task: dict[str, Any]) -> None:
    """Require the project-owned rich prompt gate at the deployed paid boundary.

    BacklotOS deliberately stays project-agnostic, but an E50+ Qingshan SD2
    task may only be paid after the active project has recompiled and checked
    every writer/director field.  Importing the project hook here means calling
    the installed submitter directly cannot bypass that contract.
    """
    episode = str(task.get("episode") or "")
    number = int(episode[1:]) if episode.startswith("E") and episode[1:].isdigit() else 0
    if number < 50 or str(task.get("model") or "").strip().lower() != "seedance-2.0-pro":
        return
    hook_path = ROOT / "tools" / "submit_giggle_video_manifest_v2.py"
    if not hook_path.is_file() or hook_path.resolve() == Path(__file__).resolve():
        raise ValueError(
            f"{task.get('task_key', 'UNKNOWN')} project-owned paid prompt lineage gate is unavailable"
        )
    module_name = "backlotos_project_video_prompt_lineage_gate"
    spec = importlib.util.spec_from_file_location(module_name, hook_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"{task.get('task_key', 'UNKNOWN')} cannot load project prompt lineage gate")
    project_root = str(ROOT)
    sys.path.insert(0, project_root)
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        validator = getattr(module, "validate_task", None)
        if not callable(validator):
            raise ValueError(f"{task.get('task_key', 'UNKNOWN')} project prompt lineage validator missing")
        validator(task)
    finally:
        if sys.path and sys.path[0] == project_root:
            sys.path.pop(0)


def validate_task(task: dict[str, Any]) -> str:
    for field in ("task_key", "prompt_file", "prompt_sha256", "reference_images", "reference_sha256"):
        if not task.get(field):
            raise ValueError(f"{task.get('task_key', 'UNKNOWN')} missing {field}")
    prompt_path = resolve(task["prompt_file"])
    if not prompt_path.is_file() or sha256(prompt_path) != task["prompt_sha256"]:
        raise ValueError(f"{task['task_key']} prompt SHA mismatch")
    prompt_text = prompt_path.read_text(encoding="utf-8")
    references = [resolve(value) for value in task["reference_images"]]
    if len(references) != len(task["reference_sha256"]):
        raise ValueError(f"{task['task_key']} reference count/SHA count mismatch")
    for path, expected in zip(references, task["reference_sha256"]):
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"{task['task_key']} reference SHA mismatch: {portable(path)}")
    episode = str(task.get("episode") or "")
    episode_number = int(episode[1:]) if episode.startswith("E") and episode[1:].isdigit() else 0
    required_model = "MiniMax-H3" if episode_number >= 45 else (
        "seedance-2.0-pro" if episode_number >= 41 else "seedance-2.0-fast"
    )
    scoped_override = task.get("owner_scoped_model_override") or {}
    override_applies = (
        scoped_override.get("schema") == "backlotos.owner_scoped_video_model_override.v1"
        and scoped_override.get("status") == "AUTHORIZED"
        and scoped_override.get("owner_authorized") is True
        and str(scoped_override.get("task_key") or "") == str(task.get("task_key") or "")
        and str(scoped_override.get("model") or "") == str(task.get("model") or "")
        and bool(str(scoped_override.get("authorization_ref") or "").strip())
        and task.get("model") in {"seedance-2.0-fast", "seedance-2.0-pro", "MiniMax-H3"}
    )
    if override_applies:
        required_model = str(task["model"])
    if task.get("model") != required_model:
        raise ValueError(f"{task['task_key']} requires {required_model} for {episode or 'this episode'}")
    required_resolution = "768p" if required_model == "MiniMax-H3" else "720p"
    if task.get("resolution") != required_resolution:
        raise ValueError(f"{task['task_key']} requires provider-native {required_resolution}")
    minimum_duration = 3 if required_model == "MiniMax-H3" else 4
    if not minimum_duration <= int(task.get("duration_seconds", 0)) <= 15:
        raise ValueError(f"{task['task_key']} duration outside {minimum_duration}-15 seconds")
    if required_model == "MiniMax-H3" and len(references) > 9:
        raise ValueError(f"{task['task_key']} MiniMax-H3 omni accepts at most 9 images")
    validate_source_caption_safe_dialogue(task, prompt_text)
    run_project_prompt_lineage_gate(task)
    return prompt_text


def task_fingerprint(task: dict[str, Any]) -> str:
    contract = {
        "task_key": task.get("task_key"),
        "prompt_sha256": task.get("prompt_sha256"),
        "reference_sha256": task.get("reference_sha256") or [],
        "reference_audio_asset_ids": task.get("reference_audio_asset_ids") or [],
        "exact_dialogue_audio_asset_ids": task.get("exact_dialogue_audio_asset_ids") or [],
        "dialogue_transport": task.get("dialogue_transport"),
        "model": task.get("model"),
        "duration": task.get("duration_seconds"),
        "aspect_ratio": task.get("aspect_ratio"),
        "resolution": task.get("resolution"),
        "transport_fingerprint": transport_fingerprint(task),
    }
    return hashlib.sha256(json.dumps(contract, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def transaction_path(transaction_dir: Path, task: dict[str, Any]) -> Path:
    return transaction_dir / f"{task['task_key']}__{task_fingerprint(task)[:16]}.json"


def validate_gate(path_value: str) -> dict[str, Any]:
    path = resolve(path_value)
    if not path.is_file():
        raise ValueError(f"Missing gate report: {path_value}")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        raise ValueError(f"Gate is not PASS: {path_value}")
    return {"path": path_value, "status": "PASS", "schema": report.get("schema")}


def prior_bound(task: dict[str, Any], transaction_dir: Path) -> dict[str, Any] | None:
    path = transaction_path(transaction_dir, task)
    if not path.is_file():
        return None
    row = json.loads(path.read_text(encoding="utf-8"))
    if row.get("submission_fingerprint") != task_fingerprint(task):
        raise RuntimeError(f"{task['task_key']} transaction fingerprint mismatch")
    if row.get("state") == "SUBMITTED_TASK_ID_BOUND" and row.get("task_id"):
        return {
            "task_key": task["task_key"],
            "task_id": row["task_id"],
            "state": "remote_running",
            "receipt": row.get("receipt"),
            "transaction": portable(path),
            "recovered_from_transaction": True,
        }
    if row.get("state") != "VERIFIED_ZERO_RETRYABLE":
        raise RuntimeError(f"{task['task_key']} blocked by transaction state {row.get('state')}")
    return None


def submit_one(task: dict[str, Any], receipt_dir: Path, transaction_dir: Path) -> dict[str, Any]:
    prior = prior_bound(task, transaction_dir)
    if prior:
        return prior
    prompt_text = validate_task(task)
    endpoint, payload = build_provider_request(
        task,
        prompt_text=prompt_text,
        root=ROOT,
        encode_image=lambda path: {"base64": _b64(path)},
    )
    transaction = transaction_path(transaction_dir, task)
    intent = {
        "schema": "qingshan.giggle_video_submit_transaction.v2",
        "task_key": task["task_key"],
        "attempt_id": str(uuid.uuid4()),
        "submission_fingerprint": task_fingerprint(task),
        "transport_endpoint": endpoint,
        "transport_fingerprint": transport_fingerprint(task),
        "state": "INTENT_RECORDED",
        "intent_recorded_at": utc_now(),
        "prompt_sha256": task["prompt_sha256"],
        "reference_sha256": task["reference_sha256"],
        "model": task["model"],
        "retry_guard": "DO_NOT_RESUBMIT_UNTIL_LEDGER_RECONCILED",
    }
    if task.get("exact_first_frame_sha256"):
        exact_index = task["reference_roles"].index("EXACT_FIRST_FRAME")
        exact_path = resolve(task["reference_images"][exact_index])
        intent["pre_encode_frame0_authority"] = {
            "source_sha256": sha256(exact_path),
            "raw_rgb_sha256": raw_rgb_sha256(exact_path),
            "transport_field": "start_frame",
        }
    atomic_json(transaction, intent)
    try:
        with paid_video_submission_context():
            response = _request(endpoint, payload)
    except (Exception, SystemExit) as exc:
        intent.update({"state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION", "response_lost_at": utc_now(), "error": str(exc)})
        atomic_json(transaction, intent)
        raise
    task_id = (response.get("data") or {}).get("task_id") or response.get("task_id")
    if not task_id:
        intent.update({"state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION", "response_lost_at": utc_now(), "error": "response missing task_id"})
        atomic_json(transaction, intent)
        raise RuntimeError("response missing task_id")
    receipt = receipt_dir / f"{task['task_key']}_submit_receipt.json"
    atomic_json(receipt, response)
    intent.update({"state": "SUBMITTED_TASK_ID_BOUND", "task_id": str(task_id), "receipt": portable(receipt), "response_recorded_at": utc_now()})
    atomic_json(transaction, intent)
    return {
        "task_key": task["task_key"],
        "task_id": str(task_id),
        "state": "remote_running",
        "transport_endpoint": endpoint,
        "required_post_harvest_gate": "exact_first_frame_post_harvest_gate" if task.get("exact_first_frame_sha256") else None,
        "receipt": portable(receipt),
        "transaction": portable(transaction),
        "recovered_from_transaction": False,
    }


def main() -> int:
    global ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--precheck-only", action="store_true")
    args = parser.parse_args()
    ROOT = configure_project_root(args.project_root)
    manifest_path = resolve(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    authoritative_gate = run_authoritative_submission_gate(manifest, manifest_path)
    gates = [validate_gate(value) for value in manifest.get("machine_gate_reports") or []]
    tasks = manifest.get("tasks") or []
    if not gates or not tasks:
        raise SystemExit("Video manifest requires passing gates and tasks")
    for task in tasks:
        validate_task(task)
        build_provider_request(task, prompt_text=resolve(task["prompt_file"]).read_text(encoding="utf-8"), root=ROOT, encode_image=lambda path: {"base64": "PRECHECK"})
    if not args.precheck_only and not os.environ.get("GIGGLE_API_KEY", "").strip():
        raise SystemExit("GIGGLE_API_KEY is not set")
    out = resolve(args.out)
    receipts = out.parent / f"{out.stem}_receipts"
    transactions = ROOT / "workflow/tasks/giggle_video_submit_transactions" / str(manifest.get("episode") or "UNKNOWN")
    start = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if args.precheck_only:
        results = [{"task_key": task["task_key"], "state": "precheck_pass", "transport_fingerprint": transport_fingerprint(task)} for task in tasks]
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            futures = {pool.submit(submit_one, task, receipts, transactions): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                try:
                    results.append(future.result())
                except (Exception, SystemExit) as exc:
                    failures.append({"task_key": task["task_key"], "state": "submit_response_lost", "error": str(exc), "transaction": portable(transaction_path(transactions, task))})
    credit = None
    ambiguity = "NOT_APPLICABLE"
    if not args.precheck_only:
        newly_bound = sum(not row.get("recovered_from_transaction") for row in results)
        maximum = newly_bound + len(failures)
        for attempt in range(7):
            credit = reconcile_rows(fetch_pay_statements(), start=start - timedelta(seconds=10), end=datetime.now(timezone.utc) + timedelta(seconds=10), expected_count=maximum, event_description="SingleGenerateVideo", model=str(tasks[0]["model"]))
            if int(credit.get("matched_count", 0)) >= newly_bound or attempt == 6:
                break
            time.sleep(5)
        ambiguity = "NO_AMBIGUOUS_SUBMISSIONS" if not failures else "QUARANTINE_AMBIGUOUS_TASKS"
    report = {
        "schema": "backlotos.giggle_video_batch_submit.v3",
        "episode": manifest.get("episode"),
        "manifest": portable(manifest_path),
        "manifest_sha256": sha256(manifest_path),
        "recorded_at": utc_now(),
        "precheck_only": args.precheck_only,
        "machine_gates": gates,
        "authoritative_production_gate": authoritative_gate,
        "status": "PASS" if len(results) == len(tasks) and not failures and (
            args.precheck_only or (credit or {}).get("status") in {"PASS", "PASS_BOUNDED"}
        ) else "FAIL",
        "submitted": sum(row.get("state") == "remote_running" for row in results),
        "precheck_pass": sum(row.get("state") == "precheck_pass" for row in results),
        "failed": len(failures),
        "tasks": sorted(results, key=lambda row: row["task_key"]),
        "failures": sorted(failures, key=lambda row: row["task_key"]),
        "credit_reconciliation": credit,
        "ambiguity_resolution": ambiguity,
        "duplicate_submit_policy": "TASK_AND_TRANSPORT_FINGERPRINT_DURABLE_TRANSACTION_GUARD",
    }
    atomic_json(out, report)
    print(json.dumps({key: report[key] for key in ("status", "submitted", "precheck_pass", "failed")}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
