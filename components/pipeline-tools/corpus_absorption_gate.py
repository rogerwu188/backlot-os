#!/usr/bin/env python3
"""Fail closed until every source asset has an auditable training disposition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FINAL_DECISIONS = {"ADAPTED", "EXCLUDED"}
SOURCE_TYPES = {"prompt", "character", "character_state", "scene", "scene_state", "shot", "media", "relation"}


def require(value, message: str):
    if value is None or value == "":
        raise ValueError(message)
    return value


def validate_manifest(payload: dict) -> dict:
    expected = int(require(payload.get("expected_source_assets"), "expected_source_assets is required"))
    records = require(payload.get("records"), "records are required")
    if not isinstance(records, list):
        raise ValueError("records must be a list")

    seen, pending, admitted, excluded = set(), [], 0, 0
    for index, row in enumerate(records, start=1):
        asset_id = require(row.get("source_asset_id"), f"record {index} source_asset_id is required")
        if asset_id in seen:
            raise ValueError(f"duplicate source_asset_id: {asset_id}")
        seen.add(asset_id)
        require(row.get("source_url"), f"record {asset_id} source_url is required")
        source_type = require(row.get("source_type"), f"record {asset_id} source_type is required")
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"record {asset_id} has unsupported source_type")
        decision = require(row.get("decision"), f"record {asset_id} decision is required")
        if decision not in FINAL_DECISIONS:
            pending.append(asset_id)
            continue
        if decision == "EXCLUDED":
            require(row.get("exclusion_reason"), f"excluded record {asset_id} needs exclusion_reason")
            excluded += 1
            continue
        digest = require(row.get("sha256"), f"adapted record {asset_id} sha256 is required")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"adapted record {asset_id} sha256 must be lowercase SHA-256")
        require(row.get("license_basis"), f"adapted record {asset_id} license_basis is required")
        require(row.get("dataset_version"), f"adapted record {asset_id} dataset_version is required")
        require(row.get("adapter_version"), f"adapted record {asset_id} adapter_version is required")
        require(row.get("evaluation_receipt"), f"adapted record {asset_id} evaluation_receipt is required")
        relations = row.get("relations", [])
        if not isinstance(relations, list):
            raise ValueError(f"record {asset_id} relations must be a list")
        admitted += 1

    missing = max(expected - len(seen), 0)
    failures = []
    if len(seen) != expected:
        failures.append(f"coverage mismatch: expected {expected}, found {len(seen)} unique records")
    if pending:
        failures.append(f"{len(pending)} records have no final ADAPTED/EXCLUDED disposition")
    return {
        "status": "PASS" if not failures else "BLOCKED",
        "expected_source_assets": expected,
        "recorded_unique_assets": len(seen),
        "adapted_assets": admitted,
        "excluded_assets": excluded,
        "pending_assets": len(pending),
        "missing_assets": missing,
        "failures": failures,
        "completion_policy": "EVERY_SOURCE_ASSET_ADAPTED_OR_EXCLUDED_WITH_REASON",
        "weight_claim": payload.get("weight_claim", "PROMPT_RULE_ADAPTER_ONLY"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    raise SystemExit(0 if result["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
