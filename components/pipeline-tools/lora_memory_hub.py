#!/usr/bin/env python3
"""Receive portable prompt memory, store it in S3, and converge it to GitHub."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from .local_lora_memory_sync import _load, _write_dataset, synchronize
except ImportError:
    from local_lora_memory_sync import _load, _write_dataset, synchronize


HUB_STATE_LOCK = threading.Lock()
HUB_STATE = {
    "lastAttemptUnix": None,
    "lastSuccessUnix": None,
    "lastStatus": "STARTING",
    "lastErrorType": None,
}


def update_hub_state(*, status: str, error: Exception | None = None) -> None:
    now = int(time.time())
    with HUB_STATE_LOCK:
        HUB_STATE["lastAttemptUnix"] = now
        HUB_STATE["lastStatus"] = status
        HUB_STATE["lastErrorType"] = type(error).__name__ if error else None
        if error is None:
            HUB_STATE["lastSuccessUnix"] = now


def hub_state() -> dict:
    with HUB_STATE_LOCK:
        return dict(HUB_STATE)


def canonical_submission(payload: dict) -> tuple[bytes, str]:
    if payload.get("schema") != "backlotos.lora_memory_submission.v1":
        raise ValueError("unsupported submission schema")
    samples = payload.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("samples must be a non-empty list")
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "submission.jsonl"
        source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in samples), encoding="utf-8")
        rows = _load(source)
        canonical = Path(directory) / "canonical.jsonl"
        digest = _write_dataset(canonical, rows)
        body = canonical.read_bytes()
    declared = str(payload.get("datasetSha256") or "")
    if declared and declared != hashlib.sha256(body).hexdigest():
        raise ValueError("dataset SHA does not match canonical samples")
    return body, digest


class S3MemoryStore:
    def __init__(self, bucket: str, prefix: str = "backlotos-lora-memory", endpoint_url: str | None = None):
        import boto3
        self.client = boto3.client("s3", endpoint_url=endpoint_url or None)
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def accept(self, body: bytes, digest: str) -> str:
        key = f"{self.prefix}/inbox/sha256/{digest}.jsonl"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType="application/x-ndjson",
                               Metadata={"sha256": digest, "schema": "backlotos-lora-memory-v1"})
        return key

    def pending(self) -> list[tuple[str, bytes]]:
        prefix = f"{self.prefix}/inbox/sha256/"
        paginator = self.client.get_paginator("list_objects_v2")
        rows = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                rows.append((key, self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()))
        return rows

    def mark_processed(self, keys: list[str], commit: str) -> None:
        receipt = json.dumps({"schema": "backlotos.lora_memory_hub_receipt.v1", "keys": keys,
                              "githubCommit": commit, "processedUnix": int(time.time())}, sort_keys=True).encode()
        digest = hashlib.sha256(receipt).hexdigest()
        self.client.put_object(Bucket=self.bucket, Key=f"{self.prefix}/processed/{digest}.json",
                               Body=receipt, ContentType="application/json")
        for key in keys:
            self.client.delete_object(Bucket=self.bucket, Key=key)


def converge_once(store: S3MemoryStore, checkout: Path) -> dict:
    pending = store.pending()
    if not pending:
        return {"status": "IDLE", "sampleCount": 0}
    with tempfile.TemporaryDirectory() as directory:
        aggregate: dict[str, dict] = {}
        for index, (_, body) in enumerate(pending):
            path = Path(directory) / f"input-{index}.jsonl"
            path.write_bytes(body)
            for sample_id, row in _load(path).items():
                if sample_id in aggregate and aggregate[sample_id] != row:
                    raise ValueError(f"immutable sample_id conflict in S3 inbox: {sample_id}")
                aggregate[sample_id] = row
        source = Path(directory) / "merged.jsonl"
        _write_dataset(source, aggregate)
        result = synchronize(source, checkout, push=True)
    store.mark_processed([key for key, _ in pending], str(result.get("commit") or ""))
    return {**result, "processedObjectCount": len(pending)}


class HubHandler(BaseHTTPRequestHandler):
    store: S3MemoryStore
    token: str

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._json(200, {"status": "PASS", "convergence": hub_state()}) if self.path == "/health" else self._json(404, {"status": "NOT_FOUND"})

    def do_POST(self):
        if self.path != "/v1/memory":
            return self._json(404, {"status": "NOT_FOUND"})
        if self.token and self.headers.get("Authorization") != f"Bearer {self.token}":
            return self._json(401, {"status": "UNAUTHORIZED"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2_000_000:
                raise ValueError("invalid submission size")
            body, digest = canonical_submission(json.loads(self.rfile.read(length)))
            key = self.store.accept(body, digest)
            self._json(202, {"status": "ACCEPTED", "datasetSha256": digest, "objectKey": key})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"status": "REJECTED", "error": str(exc)})

    def log_message(self, *_):
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--converge-once", action="store_true")
    args = parser.parse_args()
    bucket = os.environ["BACKLOTOS_LORA_S3_BUCKET"]
    checkout = Path(os.environ["BACKLOTOS_LORA_GITHUB_CHECKOUT"])
    store = S3MemoryStore(
        bucket,
        os.environ.get("BACKLOTOS_LORA_S3_PREFIX", "backlotos-lora-memory"),
        os.environ.get("BACKLOTOS_LORA_S3_ENDPOINT"),
    )
    if args.converge_once:
        print(json.dumps(converge_once(store, checkout), ensure_ascii=False))
        return
    interval = max(60, int(os.environ.get("BACKLOTOS_LORA_CONVERGE_INTERVAL_SECONDS", "900")))
    collector_token = os.environ.get("BACKLOTOS_LORA_COLLECTOR_TOKEN", "").strip()
    if not collector_token:
        raise RuntimeError("BACKLOTOS_LORA_COLLECTOR_TOKEN is required")
    def worker():
        while True:
            try:
                result = converge_once(store, checkout)
                update_hub_state(status=str(result.get("status") or "PASS"))
            except Exception as exc:
                update_hub_state(status="RETRY_PENDING", error=exc)
                print(json.dumps({"event": "lora_memory_convergence_failed",
                                  "errorType": type(exc).__name__}), file=sys.stderr, flush=True)
            time.sleep(interval)
    threading.Thread(target=worker, daemon=True).start()
    HubHandler.store = store
    HubHandler.token = collector_token
    ThreadingHTTPServer((args.host, args.port), HubHandler).serve_forever()


if __name__ == "__main__":
    main()
