#!/usr/bin/env python3
"""Crash-safe, conflict-aware persistence for task-lane scheduler state."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping


_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.Lock] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class SchedulerSnapshot:
    payload: dict[str, Any]
    sha256: str


@dataclass(frozen=True)
class SchedulerWriteLease:
    state_path: Path
    lock_path: Path
    token: str
    writer_id: str


class SchedulerWriteConflict(RuntimeError):
    """Raised when two writers changed the same scheduler task."""

    def __init__(self, task_ids: list[str], expected_sha256: str, actual_sha256: str):
        self.task_ids = task_ids
        self.expected_sha256 = expected_sha256
        self.actual_sha256 = actual_sha256
        super().__init__(
            "scheduler CAS conflict on task_id(s) "
            f"{', '.join(task_ids)}; expected {expected_sha256}, found {actual_sha256}"
        )


def read_scheduler_snapshot(path: Path) -> SchedulerSnapshot:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"scheduler state must be a JSON object: {path}")
    return SchedulerSnapshot(payload=payload, sha256=_sha256(raw))


def durable_atomic_json(path: Path, payload: dict[str, Any]) -> str:
    """Write JSON through a same-directory temp file and fsync both file and directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return _sha256(encoded)


def _thread_lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def scheduler_write_lease(
    state_path: Path,
    *,
    writer_id: str | None = None,
    timeout_seconds: float = 10.0,
    lease_seconds: float = 30.0,
) -> Iterator[SchedulerWriteLease]:
    """Hold the scheduler's process/thread single-writer lease.

    ``flock`` is authoritative and is released by the OS after a crash. The
    JSON lock-file body is an observable lease receipt, not a stale-lock
    authority, so an expired receipt can never break a live writer's lock.
    """

    state_path = state_path.resolve()
    lock_path = state_path.with_name(f".{state_path.name}.write.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    thread_lock = _thread_lock_for(lock_path)
    deadline = time.monotonic() + timeout_seconds
    if not thread_lock.acquire(timeout=max(0.0, timeout_seconds)):
        raise TimeoutError(f"scheduler writer lease timeout: {state_path}")

    descriptor: int | None = None
    lease: SchedulerWriteLease | None = None
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"scheduler writer lease timeout: {state_path}")
                time.sleep(0.01)

        token = uuid.uuid4().hex
        owner = writer_id or f"pid:{os.getpid()}"
        acquired_at = datetime.now(timezone.utc)
        receipt = {
            "schema": "backlotos.scheduler_write_lease.v1",
            "state_path": str(state_path),
            "writer_id": owner,
            "pid": os.getpid(),
            "token": token,
            "acquired_at": acquired_at.isoformat().replace("+00:00", "Z"),
            "expires_at": (acquired_at + timedelta(seconds=lease_seconds))
            .isoformat()
            .replace("+00:00", "Z"),
        }
        encoded = (
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, encoded)
        os.fsync(descriptor)
        lease = SchedulerWriteLease(state_path, lock_path, token, owner)
        yield lease
    finally:
        if descriptor is not None:
            if lease is not None:
                released = {
                    "schema": "backlotos.scheduler_write_lease.v1",
                    "state_path": str(state_path),
                    "writer_id": lease.writer_id,
                    "pid": os.getpid(),
                    "token": lease.token,
                    "released_at": _now(),
                }
                encoded = (json.dumps(released, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                try:
                    os.ftruncate(descriptor, 0)
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    os.write(descriptor, encoded)
                    os.fsync(descriptor)
                finally:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        thread_lock.release()


def _tasks_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for task in payload.get("tasks") or []:
        task_id = str(task.get("task_id") or "")
        if not task_id:
            raise ValueError("scheduler task is missing task_id")
        if task_id in result:
            raise ValueError(f"duplicate scheduler task_id: {task_id}")
        result[task_id] = task
    return result


def _merge_mapping(target: dict[str, Any], updates: Mapping[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _merge_mapping(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def commit_task_updates(
    state_path: Path,
    *,
    base_snapshot: SchedulerSnapshot,
    task_updates: Mapping[str, dict[str, Any]],
    top_level_updates: Mapping[str, Any] | None = None,
    writer_id: str | None = None,
    lease: SchedulerWriteLease | None = None,
) -> dict[str, Any]:
    """CAS scheduler state, reloading and merging disjoint task changes on conflict."""

    state_path = state_path.resolve()
    if lease is not None and lease.state_path != state_path:
        raise ValueError("scheduler lease does not match state path")
    lease_context = nullcontext(lease) if lease is not None else scheduler_write_lease(
        state_path, writer_id=writer_id
    )
    with lease_context:
        current = read_scheduler_snapshot(state_path)
        merge_mode = current.sha256 != base_snapshot.sha256
        base_tasks = _tasks_by_id(base_snapshot.payload)
        current_tasks = _tasks_by_id(current.payload)
        conflicts: list[str] = []

        if merge_mode:
            for task_id, proposed in task_updates.items():
                base_task = base_tasks.get(task_id)
                current_task = current_tasks.get(task_id)
                if current_task != base_task and current_task != proposed:
                    conflicts.append(task_id)
        if conflicts:
            raise SchedulerWriteConflict(
                sorted(conflicts), base_snapshot.sha256, current.sha256
            )

        merged = copy.deepcopy(current.payload)
        merged_tasks = merged.setdefault("tasks", [])
        positions = {
            str(task.get("task_id") or ""): index for index, task in enumerate(merged_tasks)
        }
        for task_id, proposed in task_updates.items():
            replacement = copy.deepcopy(proposed)
            if task_id in positions:
                merged_tasks[positions[task_id]] = replacement
            else:
                positions[task_id] = len(merged_tasks)
                merged_tasks.append(replacement)
        if top_level_updates:
            _merge_mapping(merged, top_level_updates)

        new_sha256 = durable_atomic_json(state_path, merged)
        return {
            "status": "COMMITTED_RELOAD_MERGE" if merge_mode else "COMMITTED_CAS",
            "expected_sha256": base_snapshot.sha256,
            "observed_sha256": current.sha256,
            "new_sha256": new_sha256,
            "task_ids": sorted(task_updates),
        }
