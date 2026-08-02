"""Idempotent job dispatch against the append-only jobs.ndjson ledger.

Ledger record shape (backlotos.producer-job/1.0):
  {schema, event_id, idempotency_key, episode_id, stage, agent, payload_sha256,
   status: QUEUED|DISPATCHED|COMPLETED|FAILED|BLOCKED, reason, timestamp,
   attempts, result}

A dispatch call is idempotent on (episode_id, stage, payload content). The
same idempotency_key dispatched twice returns the existing latest record with
deduped=True and does NOT invoke the downstream agent a second time.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .invoker import AgentInvoker, CapabilityError
from .ledger import append_ndjson, is_hex64, latest_by_key, read_ndjson, sha256_hex, utc_now
from .plan import STAGE_OWNER

JOB_SCHEMA = "backlotos.producer-job/1.0"

_KEY_LOCKS: dict[tuple, threading.Lock] = {}
_KEY_LOCKS_META = threading.Lock()


def _lock_for(project_path, key: str) -> threading.Lock:
    lock_key = (str(project_path), key)
    with _KEY_LOCKS_META:
        lock = _KEY_LOCKS.get(lock_key)
        if lock is None:
            lock = threading.Lock()
            _KEY_LOCKS[lock_key] = lock
        return lock


def idempotency_key(episode_id: str, stage: str, payload: dict) -> str:
    content_sha = sha256_hex(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    return sha256_hex(f"{episode_id}|{stage}|{content_sha}")


def _jobs_path(project_path: str | Path) -> Path:
    return Path(project_path) / "jobs.ndjson"


def _latest_jobs(project_path: str | Path) -> dict[str, dict]:
    return latest_by_key(read_ndjson(_jobs_path(project_path)), "idempotency_key")


def dispatch_job(
    project_path: str | Path,
    episode_id: str,
    stage: str,
    payload: dict,
    invoker: AgentInvoker,
    *,
    agent: str | None = None,
    force: bool = False,
    attempts_hint: int = 0,
) -> dict:
    """Dispatch one (episode_id, stage) job idempotently. Returns the ledger record (plus deduped flag).

    Serialized per (project_path, idempotency_key) so concurrent dispatch calls
    for the SAME key never invoke the downstream agent more than once."""
    agent = agent or STAGE_OWNER.get(stage, "unknown")
    key = idempotency_key(episode_id, stage, payload)
    lock = _lock_for(project_path, key)
    with lock:
        latest = _latest_jobs(project_path)
        existing = latest.get(key)
        if existing and not force:
            return {**existing, "deduped": True}

        attempts = (existing.get("attempts", 0) + 1) if existing else 1
        record = {
            "schema": JOB_SCHEMA,
            "event_id": sha256_hex(f"{key}|{utc_now()}|{attempts}")[:20],
            "idempotency_key": key,
            "episode_id": episode_id,
            "stage": stage,
            "agent": agent,
            "payload_sha256": sha256_hex(json.dumps(payload, sort_keys=True, ensure_ascii=False)),
            "payload": payload,
            "timestamp": utc_now(),
            "attempts": attempts,
            "deduped": False,
        }
        if agent == "human":
            record.update(status="BLOCKED", reason="HUMAN_AUTHORIZATION_REQUIRED", result=None)
            append_ndjson(_jobs_path(project_path), record)
            return record
        try:
            result = invoker.invoke(agent, payload)
        except CapabilityError as exc:
            record.update(status="BLOCKED", reason="CAPABILITY_FAIL", error=str(exc), result=None)
            append_ndjson(_jobs_path(project_path), record)
            return record
        result_status = str(result.get("status", "")).upper()
        failure_statuses = {"FAIL", "FAILED", "ERROR", "CAPABILITY_FAIL", "ADAPTER_REQUIRED", "BLOCKED", "NOT_RUN"}
        ok = bool(result.get("ok", False)) and result_status not in failure_statuses
        record.update(
            status="COMPLETED" if ok else "FAILED",
            reason=None if ok else result.get("status", "AGENT_REPORTED_FAILURE"),
            result=result,
        )
        append_ndjson(_jobs_path(project_path), record)
        return record


def resume_plan(project_path: str | Path) -> dict:
    """Read plan.json + jobs.ndjson and compute the next actionable stage per episode
    without re-dispatching already-COMPLETED jobs. Read-only / safe after an
    interrupted run."""
    project_path = Path(project_path)
    plan_path = project_path / "plan.json"
    if not plan_path.is_file():
        return {"ok": False, "status": "ERROR", "error": "plan.json not found; call plan first"}
    with plan_path.open(encoding="utf-8") as stream:
        plan = json.load(stream)
    jobs = read_ndjson(_jobs_path(project_path))
    # For resume we key by (episode_id, stage) -> latest status, taking the most
    # recently timestamped record per (episode_id, stage) regardless of payload hash,
    # since a stage may have been dispatched with slightly different payloads across attempts.
    latest_stage_status: dict[tuple[str, str], dict] = {}
    for job in jobs:
        key = (job.get("episode_id"), job.get("stage"))
        prior = latest_stage_status.get(key)
        if prior is None or job.get("timestamp", "") >= prior.get("timestamp", ""):
            latest_stage_status[key] = job

    next_actions = []
    for episode in plan.get("episodes", []):
        episode_id = episode["episode_id"]
        sequence = episode.get("stage_sequence", [])
        next_stage = None
        for stage in sequence:
            record = latest_stage_status.get((episode_id, stage))
            if record and record.get("status") == "COMPLETED":
                continue
            next_stage = stage
            break
        next_actions.append({
            "episode_id": episode_id,
            "next_stage": next_stage,
            "completed_stages": [s for s in sequence if latest_stage_status.get((episode_id, s), {}).get("status") == "COMPLETED"],
        })
    return {"ok": True, "status": "RESUMED", "next_actions": next_actions}


def retry_failed(project_path: str | Path, invoker: AgentInvoker) -> dict:
    """Re-dispatch ONLY jobs whose latest state (by idempotency_key) is FAILED.
    COMPLETED and BLOCKED (pending-human / capability) jobs are never touched."""
    latest = _latest_jobs(project_path)
    retried = []
    for key, record in latest.items():
        if record.get("status") != "FAILED":
            continue
        payload = {"__retry_of_event_id__": record.get("event_id")}
        # We do not have the original payload content (only its sha256) so we
        # replay using the stored payload if present, else the sha marker;
        # real deployments should store the payload_ref alongside the job.
        original_payload = record.get("payload") or payload
        new_record = dispatch_job(
            project_path, record["episode_id"], record["stage"], original_payload,
            invoker, agent=record.get("agent"), force=True,
        )
        retried.append(new_record)
    return {"ok": True, "status": "RETRY_COMPLETE", "retried_count": len(retried), "retried": retried}
