#!/usr/bin/env python3
"""Merge and optionally publish portable BacklotOS LoRA-ready prompt memory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


DATASET_RELATIVE = Path("components/pipeline-tools/local_lora/seedance2_prompt_failure_training.jsonl")
MANIFEST_RELATIVE = Path("components/pipeline-tools/local_lora/seedance2_prompt_memory_manifest.json")
ALLOWED_FIELDS = {
    "schema", "sample_id", "status", "generation_mode", "applicable_modes",
    "failure_evidence", "failed_prompt_sha256", "failed_asset_sha256",
    "root_cause", "optimization", "accepted_evidence", "accepted_prompt_sha256",
    "accepted_asset_sha256", "compiler_guard_clause", "tags",
}
FORBIDDEN_KEY_PARTS = {"token", "secret", "password", "credential", "cookie", "authorization", "api_key"}


def _run(argv: list[str], cwd: Path) -> str:
    completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(f"{' '.join(argv)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _load(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if not path.is_file():
        return rows
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        unknown = set(raw) - ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"line {line_number} contains non-portable fields: {', '.join(sorted(unknown))}")
        if any(any(part in key.lower() for part in FORBIDDEN_KEY_PARTS) for key in raw):
            raise ValueError(f"line {line_number} contains a credential-like field")
        sample_id = str(raw.get("sample_id") or "").strip()
        if not sample_id or raw.get("status") != "ADMITTED":
            raise ValueError(f"line {line_number} must be an ADMITTED sample with sample_id")
        for evidence_key in ("failure_evidence", "accepted_evidence"):
            evidence = str(raw.get(evidence_key) or "")
            if evidence and not evidence.startswith("redacted://"):
                raise ValueError(f"line {line_number} {evidence_key} must use redacted:// evidence")
        for key, value in raw.items():
            if isinstance(value, str) and (value.startswith("/") or "file://" in value.lower()):
                raise ValueError(f"line {line_number} contains a local path in {key}")
        canonical = json.loads(json.dumps(raw, ensure_ascii=False, sort_keys=True))
        previous = rows.get(sample_id)
        if previous is not None and previous != canonical:
            raise ValueError(f"conflicting duplicate sample_id in {path}: {sample_id}")
        rows[sample_id] = canonical
    return rows


def _write_dataset(path: Path, rows: dict[str, dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(rows[key], ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for key in sorted(rows))
    path.write_text(body, encoding="utf-8")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def synchronize(source: Path, checkout: Path, *, push: bool) -> dict:
    checkout = checkout.resolve()
    if not (checkout / ".git").exists():
        raise ValueError(f"sync checkout is not a Git repository: {checkout}")
    destination = checkout / DATASET_RELATIVE
    if push:
        _run(["git", "pull", "--rebase", "--autostash"], checkout)
    local_rows = _load(source.resolve())
    remote_rows = _load(destination)
    merged = dict(remote_rows)
    for sample_id, row in local_rows.items():
        if sample_id in merged and merged[sample_id] != row:
            raise ValueError(f"immutable sample_id conflict across machines: {sample_id}")
        merged[sample_id] = row
    dataset_sha = _write_dataset(destination, merged)
    manifest_path = checkout / MANIFEST_RELATIVE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    manifest.update({
        "schema": "backlotos.seedance_prompt_memory_manifest.v1",
        "format": "LoRA-ready JSONL plus deterministic compiler retrieval",
        "training_status": "RULE_ADAPTER_ACTIVE_WEIGHT_TRAINING_NOT_CLAIMED",
        "dataset": DATASET_RELATIVE.name,
        "sample_count": len(merged),
        "dataset_sha256": dataset_sha,
        "sync_policy": "PRIVACY_FILTERED_CONTENT_ADDRESSED_GITHUB_CONVERGENCE",
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    changed = bool(_run(["git", "status", "--porcelain", "--", str(DATASET_RELATIVE), str(MANIFEST_RELATIVE)], checkout))
    commit = None
    if push and changed:
        _run(["git", "add", "--", str(DATASET_RELATIVE), str(MANIFEST_RELATIVE)], checkout)
        _run(["git", "commit", "-m", f"sync LoRA prompt memory ({len(merged)} samples)"], checkout)
        _run(["git", "push"], checkout)
        commit = _run(["git", "rev-parse", "HEAD"], checkout)
    return {"status": "PASS", "sampleCount": len(merged), "datasetSha256": dataset_sha,
            "changed": changed, "pushed": bool(push and changed), "commit": commit}


def auto_sync(source: Path) -> dict:
    if os.environ.get("BACKLOTOS_LORA_AUTO_SYNC") != "1":
        return {"status": "NOT_CONFIGURED", "pushed": False}
    checkout = os.environ.get("BACKLOTOS_LORA_SYNC_CHECKOUT")
    if not checkout:
        raise ValueError("BACKLOTOS_LORA_SYNC_CHECKOUT is required when BACKLOTOS_LORA_AUTO_SYNC=1")
    return synchronize(source, Path(checkout), push=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    print(json.dumps(synchronize(args.source, args.checkout, push=args.push), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
