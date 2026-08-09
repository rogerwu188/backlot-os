#!/usr/bin/env python3
"""Continuously dispatch task-lane work without waiting for a heartbeat.

The controller is deliberately provider-agnostic.  A READY task supplies a
typed dispatch descriptor (an argv command or an atomic event file).  The
controller persists an idempotent dispatch journal before starting work and
only then changes the scheduler state to RUNNING.  REMOTE_WAIT never consumes
a local worker slot unless the task explicitly says that it does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from task_lane_global_wait_gate import audit_scheduler_state
from task_lane_state_store import (
    SchedulerWriteLease,
    commit_task_updates,
    durable_atomic_json,
    read_scheduler_snapshot,
    scheduler_write_lease,
)


ACTIVE_LOCAL_STATES = frozenset({"RUNNING", "QA"})
SHOT_DELIVERABLES = frozenset({"SHOT_PACKAGE", "ADMITTED_VIDEO", "ASSEMBLY_READY_CLIP"})


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _running_lease_fields(task: dict[str, Any], owner: str) -> dict[str, str]:
    descriptor = task.get("dispatch") or {}
    try:
        lease_seconds = int(descriptor.get("lease_seconds", 300))
    except (TypeError, ValueError):
        lease_seconds = 300
    lease_seconds = min(max(30, lease_seconds), 86400)
    try:
        progress_seconds = int(descriptor.get("progress_interval_seconds", 30))
    except (TypeError, ValueError):
        progress_seconds = 30
    progress_seconds = min(max(1, progress_seconds), lease_seconds)
    started = datetime.now(timezone.utc)
    stamp = lambda value: value.isoformat().replace("+00:00", "Z")
    return {
        "lease_owner": owner,
        "lease_expires_at": stamp(started + timedelta(seconds=lease_seconds)),
        "last_progress_at": stamp(started),
        "next_due_at": stamp(started + timedelta(seconds=progress_seconds)),
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    durable_atomic_json(path, payload)


def _inside(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"dispatch path escapes root: {candidate}") from exc
    return resolved


def _dispatch_key(task: dict[str, Any]) -> str:
    descriptor = task.get("dispatch") or {}
    explicit = str(descriptor.get("idempotency_key") or "").strip()
    if explicit:
        return explicit
    material = json.dumps(
        {"task_id": task.get("task_id"), "dispatch": descriptor},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _priority(task: dict[str, Any], index: int) -> tuple[int, float, int]:
    deliverable = str(task.get("deliverable_type") or "")
    completion_first = 1 if deliverable in SHOT_DELIVERABLES else 0
    try:
        explicit = float(task.get("priority", 0))
    except (TypeError, ValueError):
        explicit = 0.0
    return (-completion_first, -explicit, index)


def select_ready_tasks(payload: dict[str, Any], capacity: int) -> dict[str, Any]:
    gate = audit_scheduler_state(payload)
    if gate["status"] != "PASS":
        return {"status": "BLOCKED_INVALID_SCHEDULER", "gate": gate, "selected": []}

    tasks = payload.get("tasks") or []
    active = sum(
        1
        for task in tasks
        if task.get("state") in ACTIVE_LOCAL_STATES
        or (task.get("state") == "REMOTE_WAIT" and task.get("occupies_local_slot") is True)
    )
    available = max(0, capacity - active)
    ready = [(index, task) for index, task in enumerate(tasks) if task.get("state") == "READY"]
    ready.sort(key=lambda pair: _priority(pair[1], pair[0]))
    selected = [task for _, task in ready[:available]]
    return {
        "status": "PASS",
        "gate": gate,
        "capacity": capacity,
        "active_local_slots": active,
        "available_local_slots": available,
        "selected": [str(task.get("task_id") or "") for task in selected],
        "ready_not_selected": [str(task.get("task_id") or "") for _, task in ready[available:]],
    }


def _validate_descriptor(descriptor: Any) -> list[str]:
    if not isinstance(descriptor, dict):
        return ["DISPATCH_DESCRIPTOR_MISSING"]
    kind = descriptor.get("kind")
    if kind == "event":
        failures = []
        if not isinstance(descriptor.get("event_path"), str) or not descriptor["event_path"].strip():
            failures.append("EVENT_PATH_MISSING")
        if not isinstance(descriptor.get("payload"), dict):
            failures.append("EVENT_PAYLOAD_MISSING")
        return failures
    if kind == "command":
        argv = descriptor.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(value, str) and value for value in argv):
            return ["COMMAND_ARGV_MUST_BE_NONEMPTY_STRING_LIST"]
        return []
    return ["DISPATCH_KIND_UNSUPPORTED"]


def _journal_template() -> dict[str, Any]:
    return {"schema": "backlotos.continuous_task_lane_dispatch_journal.v1", "dispatches": {}}


def _dispatch_cycle(
    state_path: Path,
    journal_path: Path,
    root: Path,
    capacity: int,
    apply: bool,
    lease: SchedulerWriteLease | None,
) -> dict[str, Any]:
    snapshot = read_scheduler_snapshot(state_path)
    payload = snapshot.payload
    selection = select_ready_tasks(payload, capacity)
    if selection["status"] != "PASS":
        return selection

    journal = read_json(journal_path) if journal_path.is_file() else _journal_template()
    journal.setdefault("dispatches", {})
    tasks_by_id = {str(task.get("task_id") or ""): task for task in payload.get("tasks") or []}
    outcomes: list[dict[str, Any]] = []
    changed = False
    changed_task_ids: set[str] = set()

    for task_id in selection["selected"]:
        task = tasks_by_id[task_id]
        descriptor = task.get("dispatch")
        failures = _validate_descriptor(descriptor)
        key = _dispatch_key(task)
        prior = journal["dispatches"].get(key)
        if failures:
            outcomes.append({"task_id": task_id, "status": "BLOCKED", "failures": failures})
            continue
        if prior and prior.get("status") == "DISPATCHED":
            if apply and task.get("state") == "READY":
                task["state"] = "RUNNING"
                task["dispatch_idempotency_key"] = key
                task["dispatch_receipt"] = prior.get("receipt")
                task.update(_running_lease_fields(task, f"dispatch-recovery:{key}"))
                changed = True
                changed_task_ids.add(task_id)
            outcomes.append({"task_id": task_id, "status": "REUSED_DURABLE_DISPATCH", "key": key})
            continue
        if not apply:
            outcomes.append({"task_id": task_id, "status": "DRY_RUN_READY", "key": key})
            continue

        intent = {
            "task_id": task_id,
            "status": "INTENT_PERSISTED",
            "created_at": now(),
            "descriptor": descriptor,
        }
        journal["dispatches"][key] = intent
        atomic_json(journal_path, journal)

        try:
            if descriptor["kind"] == "event":
                event_path = _inside(root, root / descriptor["event_path"])
                event_payload = dict(descriptor["payload"])
                event_payload.setdefault("task_id", task_id)
                event_payload.setdefault("idempotency_key", key)
                atomic_json(event_path, event_payload)
                receipt = {"kind": "event", "event_path": str(event_path)}
            else:
                cwd = _inside(root, root / str(descriptor.get("cwd") or "."))
                log_dir = _inside(root, root / ".backlotos/continuous-dispatch")
                log_dir.mkdir(parents=True, exist_ok=True)
                stdout_path = log_dir / f"{task_id}.stdout.log"
                stderr_path = log_dir / f"{task_id}.stderr.log"
                with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
                    process = subprocess.Popen(
                        descriptor["argv"],
                        cwd=cwd,
                        stdout=stdout,
                        stderr=stderr,
                        start_new_session=True,
                    )
                receipt = {
                    "kind": "command",
                    "pid": process.pid,
                    "argv": descriptor["argv"],
                    "cwd": str(cwd),
                    "stdout": str(stdout_path),
                    "stderr": str(stderr_path),
                }
        except Exception as exc:
            journal["dispatches"][key].update(
                {"status": "DISPATCH_FAILED", "failed_at": now(), "error": str(exc)}
            )
            atomic_json(journal_path, journal)
            outcomes.append({"task_id": task_id, "status": "DISPATCH_FAILED", "key": key})
            continue

        journal["dispatches"][key].update(
            {"status": "DISPATCHED", "dispatched_at": now(), "receipt": receipt}
        )
        atomic_json(journal_path, journal)
        task["state"] = "RUNNING"
        task["dispatch_started_at"] = now()
        task["dispatch_idempotency_key"] = key
        task["dispatch_receipt"] = receipt
        lease_owner = (
            f"worker-pid:{receipt['pid']}"
            if receipt["kind"] == "command"
            else f"event-dispatch:{key}"
        )
        task.update(_running_lease_fields(task, lease_owner))
        changed = True
        changed_task_ids.add(task_id)
        outcomes.append({"task_id": task_id, "status": "DISPATCHED", "key": key, "receipt": receipt})

    if changed:
        payload["recorded_at"] = now()
        payload.setdefault("scheduler_decision", {})["global_wait"] = False
        payload["scheduler_decision"]["reason"] = (
            "Continuous dispatcher claimed READY work immediately; heartbeat is watchdog-only."
        )
        state_commit = commit_task_updates(
            state_path,
            base_snapshot=snapshot,
            task_updates={task_id: tasks_by_id[task_id] for task_id in changed_task_ids},
            top_level_updates={
                "recorded_at": payload["recorded_at"],
                "scheduler_decision": {
                    "global_wait": payload["scheduler_decision"]["global_wait"],
                    "reason": payload["scheduler_decision"]["reason"],
                },
            },
            writer_id=f"continuous-dispatcher:{os.getpid()}",
            lease=lease,
        )
    else:
        state_commit = None

    status = "PASS"
    if any(outcome["status"] in {"BLOCKED", "DISPATCH_FAILED"} for outcome in outcomes):
        status = "BLOCKED"
    return {
        **selection,
        "status": status,
        "applied": apply,
        "outcomes": outcomes,
        "state_commit": state_commit,
    }


def dispatch_cycle(
    state_path: Path,
    journal_path: Path,
    root: Path,
    capacity: int,
    apply: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    state_path = _inside(root, state_path)
    journal_path = _inside(root, journal_path)
    if not apply:
        return _dispatch_cycle(state_path, journal_path, root, capacity, False, None)
    with scheduler_write_lease(
        state_path,
        writer_id=f"continuous-dispatcher:{os.getpid()}",
    ) as lease:
        return _dispatch_cycle(state_path, journal_path, root, capacity, True, lease)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--capacity", type=int, default=3)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.capacity < 1:
        parser.error("--capacity must be at least 1")
    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")

    while True:
        result = dispatch_cycle(
            args.state,
            args.journal,
            args.root,
            args.capacity,
            apply=args.apply,
        )
        if args.out:
            atomic_json(args.out.resolve(), result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not args.watch:
            return 0 if result["status"] == "PASS" else 2
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
