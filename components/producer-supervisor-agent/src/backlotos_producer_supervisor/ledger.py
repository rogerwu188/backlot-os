"""Disk primitives shared by the Producer/Supervisor runtime.

Mirrors the exact on-disk conventions already used by
``backlotos_launcher.pipeline``: atomic write-then-rename JSON files,
append-only NDJSON ledgers with fsync, UTC ISO timestamps. This module
intentionally re-implements (rather than imports) those primitives so this
package has no hard dependency on the launcher package, but the on-disk
*shapes* it writes are compatible with files pipeline.py already reads/writes
(episodes/*.json, credits.ndjson).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_WRITE_LOCK = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def is_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())


def atomic_write_json(path: Path, payload: dict | list) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".partial")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def load_json(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def append_ndjson(path: Path, record: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK, path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_ndjson(path: Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def latest_by_key(records: list[dict], key_field: str) -> dict[str, dict]:
    """Reduce an append-only ledger to the latest record per key (last write wins)."""
    latest: dict[str, dict] = {}
    for record in records:
        key = record.get(key_field)
        if key is None:
            continue
        latest[key] = record
    return latest
