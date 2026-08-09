#!/usr/bin/env python3
"""Platform-neutral, durable wake loop for the production-line agent.

The wake command must be an idempotent orchestration/checkpoint entrypoint.  It
must never be a provider submitter.  One shared state directory gives every
platform adapter the same time-slot run key, lease fence, and durable receipt.
"""
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".partial-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


def load(path, default=None):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else default


def validate(config):
    required = {"agent_id", "interval_seconds", "state_dir", "wake_command"}
    if not required <= set(config):
        raise ValueError("portable wake config missing required keys")
    if int(config["interval_seconds"]) < 30:
        raise ValueError("interval_seconds must be >= 30")
    command = config["wake_command"]
    if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
        raise ValueError("wake_command must be a non-empty argv list")
    policy = config.get("safety_policy", {})
    if policy.get("paid_submission_forbidden") is not True:
        raise ValueError("wake command must explicitly forbid paid submission")
    if policy.get("browser_and_platform_actions_forbidden") is not True:
        raise ValueError("wake command must explicitly forbid browser/platform actions")


def resolve_state_dir(config_path, configured):
    path = Path(configured)
    return path if path.is_absolute() else Path(config_path).resolve().parent / path


def run_once(config_path, now=None):
    config_path = Path(config_path).resolve()
    config = load(config_path)
    validate(config)
    now = float(time.time() if now is None else now)
    interval = int(config["interval_seconds"])
    slot = int(now) // interval
    state_dir = resolve_state_dir(config_path, config["state_dir"])
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_handle = open(state_dir / "wake.lock", "a+")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        state_path = state_dir / "state.json"
        state = load(state_path, {"fencing_token": 0, "claimed_slots": {}})
        claimed = state.setdefault("claimed_slots", {})
        slot_key = str(slot)
        if slot_key in claimed:
            return {
                "schema": "backlotos.portable_wakeup.result.v1",
                "status": "NOOP_ALREADY_WOKEN",
                "agent_id": config["agent_id"],
                "slot": slot,
                "run_key": claimed[slot_key]["run_key"],
            }
        fencing_token = int(state.get("fencing_token", 0)) + 1
        run_key = hashlib.sha256(
            f"{config['agent_id']}:{interval}:{slot}".encode()
        ).hexdigest()
        intent = {
            "schema": "backlotos.portable_wakeup.intent.v1",
            "agent_id": config["agent_id"],
            "interval_seconds": interval,
            "slot": slot,
            "run_key": run_key,
            "fencing_token": fencing_token,
            "status": "INTENT_PERSISTED",
            "created_at": now,
        }
        claimed[slot_key] = intent
        state.update({"fencing_token": fencing_token, "last_claimed_slot": slot})
        atomic(state_path, canon(state) + "\n")
        receipt_path = state_dir / "receipts" / f"{slot}-{run_key}.json"
        atomic(receipt_path, canon(intent) + "\n")
        environment = os.environ.copy()
        environment.update({str(k): str(v) for k, v in config.get("environment", {}).items()})
        environment.update(
            {
                "BACKLOTOS_WAKE_AGENT_ID": config["agent_id"],
                "BACKLOTOS_WAKE_RUN_KEY": run_key,
                "BACKLOTOS_WAKE_SLOT": slot_key,
                "BACKLOTOS_WAKE_FENCING_TOKEN": str(fencing_token),
                "BACKLOTOS_WAKE_REASON": "SCHEDULED_CHECKPOINT_NOT_COMPLETION",
            }
        )
        started = time.time()
        try:
            completed = subprocess.run(
                config["wake_command"],
                cwd=config.get("workdir"),
                env=environment,
                capture_output=True,
                text=True,
                timeout=int(config.get("timeout_seconds", max(30, interval - 5))),
                check=False,
            )
            result = {
                **intent,
                "status": "PASS" if completed.returncode == 0 else "FAIL",
                "returncode": completed.returncode,
                "stdout": completed.stdout[-4096:],
                "stderr": completed.stderr[-4096:],
                "finished_at": time.time(),
                "elapsed_seconds": round(time.time() - started, 6),
            }
        except subprocess.TimeoutExpired as exc:
            result = {
                **intent,
                "status": "TIMEOUT",
                "returncode": None,
                "stdout": (exc.stdout or "")[-4096:] if isinstance(exc.stdout, str) else "",
                "stderr": (exc.stderr or "")[-4096:] if isinstance(exc.stderr, str) else "",
                "finished_at": time.time(),
                "elapsed_seconds": round(time.time() - started, 6),
            }
        atomic(receipt_path, canon(result) + "\n")
        state = load(state_path, state)
        state["claimed_slots"][slot_key] = result
        state["last_result"] = result
        atomic(state_path, canon(state) + "\n")
        return result
    finally:
        fcntl.flock(lock_handle, fcntl.LOCK_UN)
        lock_handle.close()


def daemon(config_path):
    config = load(config_path)
    validate(config)
    interval = int(config["interval_seconds"])
    while True:
        run_once(config_path)
        now = time.time()
        next_slot = (int(now) // interval + 1) * interval
        time.sleep(max(1.0, next_slot - now))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--daemon", action="store_true")
    args = parser.parse_args()
    if args.once:
        print(canon(run_once(args.config)))
    else:
        daemon(args.config)


if __name__ == "__main__":
    main()
