#!/usr/bin/env python3
"""Fail-closed gate for paid retries after repeated generation failures.

The input is one ``backlotos.retry_strategy_change_request.v1`` document with
an ordered ``attempts`` failure ledger and one ``candidate`` retry.  Historical
rows are deliberately immutable audit facts.  The gate never submits work; it
only decides whether the proposed paid retry is admissible.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any


INPUT_SCHEMA = "backlotos.retry_strategy_change_request.v1"
OUTPUT_SCHEMA = "backlotos.retry_strategy_change_gate.v1"
ALLOWED_STRATEGIES = frozenset(
    {
        "shot_split",
        "transport_change",
        "deterministic_composite",
        "asset_isolation",
    }
)
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _failure(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, **details}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _normalized_attempt(
    row: Any,
    *,
    row_name: str,
    failures: list[dict[str, Any]],
    historical: bool,
) -> dict[str, Any]:
    if not isinstance(row, dict):
        failures.append(_failure("ATTEMPT_ROW_NOT_OBJECT", row=row_name))
        row = {}

    failure_family = row.get("failure_family")
    representation = row.get("representation")
    prompt_sha256 = row.get("prompt_sha256")
    input_sha256 = row.get("input_sha256")
    attempt = row.get("attempt")
    charged = row.get("charged")
    refund = row.get("refund")
    credit_classification = row.get("credit_classification")
    outcome = row.get("outcome")

    if not isinstance(failure_family, str) or not failure_family.strip():
        failures.append(_failure("FAILURE_FAMILY_MISSING", row=row_name))
    if not isinstance(representation, str) or not representation.strip():
        failures.append(_failure("REPRESENTATION_MISSING", row=row_name))
    if not _valid_sha256(prompt_sha256):
        failures.append(_failure("PROMPT_SHA256_INVALID", row=row_name))
    if not _valid_sha256(input_sha256):
        failures.append(_failure("INPUT_SHA256_INVALID", row=row_name))
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        failures.append(_failure("ATTEMPT_NUMBER_INVALID", row=row_name))
    if not _is_number(charged) or charged < 0:
        failures.append(_failure("CHARGED_INVALID", row=row_name))
    if not _is_number(refund) or refund < 0:
        failures.append(_failure("REFUND_INVALID", row=row_name))
    if _is_number(charged) and _is_number(refund) and refund > charged:
        failures.append(_failure("REFUND_EXCEEDS_CHARGED", row=row_name))
    if not isinstance(credit_classification, str) or not credit_classification.strip():
        failures.append(_failure("CREDIT_CLASSIFICATION_MISSING", row=row_name))

    expected_outcome = "FAILED" if historical else "NOT_SUBMITTED"
    if outcome != expected_outcome:
        failures.append(
            _failure(
                "OUTCOME_INVALID",
                row=row_name,
                expected=expected_outcome,
                actual=outcome,
            )
        )

    return {
        "failure_family": failure_family.strip() if isinstance(failure_family, str) else None,
        "representation": representation.strip() if isinstance(representation, str) else None,
        "prompt_sha256": prompt_sha256.lower() if _valid_sha256(prompt_sha256) else None,
        "input_sha256": input_sha256.lower() if _valid_sha256(input_sha256) else None,
        "attempt": attempt if isinstance(attempt, int) and not isinstance(attempt, bool) else None,
        "charged": charged if _is_number(charged) else None,
        "refund": refund if _is_number(refund) else None,
        "credit_classification": credit_classification.strip()
        if isinstance(credit_classification, str)
        else None,
        "outcome": outcome,
    }


def _credit_is_reconciled(row: dict[str, Any]) -> tuple[bool, str]:
    charged = row.get("charged")
    refund = row.get("refund")
    classification = row.get("credit_classification")
    if not _is_number(charged) or not _is_number(refund):
        return False, "INVALID_CREDIT_FACTS"
    if classification == "VERIFIED_ZERO" and charged == 0 and refund == 0:
        return True, "VERIFIED_ZERO"
    if charged > 0 and refund == charged:
        return True, "FULL_REFUND"
    return False, "UNRECONCILED"


def _validate_strategy_change(
    strategy: Any,
    *,
    predecessor: dict[str, Any],
    candidate: dict[str, Any],
    failures: list[dict[str, Any]],
    required: bool,
) -> dict[str, Any] | None:
    if strategy is None:
        if required:
            failures.append(_failure("STRATEGY_CHANGE_REQUIRED_AFTER_TWO_FAILURES"))
        return None
    if not isinstance(strategy, dict):
        failures.append(_failure("STRATEGY_CHANGE_NOT_OBJECT"))
        return None

    kind = strategy.get("kind")
    validated = strategy.get("validated")
    evidence_sha256 = strategy.get("evidence_sha256")
    from_representation = strategy.get("from_representation")
    to_representation = strategy.get("to_representation")

    if kind not in ALLOWED_STRATEGIES:
        failures.append(
            _failure(
                "STRATEGY_CHANGE_KIND_INVALID",
                actual=kind,
                allowed=sorted(ALLOWED_STRATEGIES),
            )
        )
    if validated is not True:
        failures.append(_failure("STRATEGY_CHANGE_NOT_VALIDATED"))
    if not _valid_sha256(evidence_sha256):
        failures.append(_failure("STRATEGY_CHANGE_EVIDENCE_SHA256_INVALID"))
    if from_representation != predecessor.get("representation"):
        failures.append(
            _failure(
                "STRATEGY_CHANGE_FROM_REPRESENTATION_MISMATCH",
                expected=predecessor.get("representation"),
                actual=from_representation,
            )
        )
    if to_representation != candidate.get("representation"):
        failures.append(
            _failure(
                "STRATEGY_CHANGE_TO_REPRESENTATION_MISMATCH",
                expected=candidate.get("representation"),
                actual=to_representation,
            )
        )
    if kind == "transport_change" and from_representation == to_representation:
        failures.append(_failure("TRANSPORT_CHANGE_MUST_CHANGE_REPRESENTATION"))

    return {
        "kind": kind,
        "validated": validated is True,
        "evidence_sha256": evidence_sha256.lower() if _valid_sha256(evidence_sha256) else None,
        "from_representation": from_representation,
        "to_representation": to_representation,
    }


def audit_retry_request(payload: Any) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        payload = {}
        failures.append(_failure("INPUT_NOT_OBJECT"))
    if payload.get("schema") != INPUT_SCHEMA:
        failures.append(_failure("UNSUPPORTED_SCHEMA", actual=payload.get("schema")))

    scope_id = payload.get("scope_id")
    if not isinstance(scope_id, str) or not scope_id.strip():
        failures.append(_failure("SCOPE_ID_MISSING"))

    raw_attempts = payload.get("attempts")
    if not isinstance(raw_attempts, list) or not raw_attempts:
        failures.append(_failure("ATTEMPTS_MISSING_OR_EMPTY"))
        raw_attempts = []
    attempts = [
        _normalized_attempt(row, row_name=f"attempts[{index}]", failures=failures, historical=True)
        for index, row in enumerate(raw_attempts)
    ]
    candidate = _normalized_attempt(
        payload.get("candidate"),
        row_name="candidate",
        failures=failures,
        historical=False,
    )

    paid_submission = payload.get("candidate", {}).get("paid_submission") if isinstance(payload.get("candidate"), dict) else None
    if paid_submission is not True:
        failures.append(_failure("CANDIDATE_PAID_SUBMISSION_MUST_BE_TRUE"))
    if candidate.get("charged") != 0 or candidate.get("refund") != 0:
        failures.append(_failure("CANDIDATE_MUST_BE_UNCHARGED_BEFORE_SUBMISSION"))
    if candidate.get("credit_classification") != "NOT_SUBMITTED":
        failures.append(_failure("CANDIDATE_CREDIT_CLASSIFICATION_MUST_BE_NOT_SUBMITTED"))

    numbers = [row["attempt"] for row in attempts if isinstance(row.get("attempt"), int)]
    duplicate_numbers = sorted({number for number in numbers if numbers.count(number) > 1})
    if duplicate_numbers:
        failures.append(_failure("DUPLICATE_ATTEMPT_NUMBER", attempts=duplicate_numbers))

    retry_of_attempt = payload.get("candidate", {}).get("retry_of_attempt") if isinstance(payload.get("candidate"), dict) else None
    if not isinstance(retry_of_attempt, int) or isinstance(retry_of_attempt, bool) or retry_of_attempt < 1:
        failures.append(_failure("RETRY_OF_ATTEMPT_INVALID"))
        predecessor = None
    else:
        predecessor = next((row for row in attempts if row.get("attempt") == retry_of_attempt), None)
        if predecessor is None:
            failures.append(_failure("RETRY_PREDECESSOR_NOT_FOUND", retry_of_attempt=retry_of_attempt))

    if numbers and retry_of_attempt != max(numbers):
        failures.append(
            _failure(
                "RETRY_PREDECESSOR_MUST_BE_LATEST_ATTEMPT",
                expected=max(numbers),
                actual=retry_of_attempt,
            )
        )
    if numbers and candidate.get("attempt") != max(numbers) + 1:
        failures.append(
            _failure(
                "CANDIDATE_ATTEMPT_NOT_SEQUENTIAL",
                expected=max(numbers) + 1,
                actual=candidate.get("attempt"),
            )
        )

    matching_failure_count = 0
    credit_resolution = "NO_PREDECESSOR"
    strategy = None
    if predecessor is not None:
        if candidate.get("failure_family") != predecessor.get("failure_family"):
            failures.append(
                _failure(
                    "CANDIDATE_FAILURE_FAMILY_MISMATCH",
                    expected=predecessor.get("failure_family"),
                    actual=candidate.get("failure_family"),
                )
            )

        reconciled, credit_resolution = _credit_is_reconciled(predecessor)
        if not reconciled:
            failures.append(
                _failure(
                    "PREDECESSOR_CREDIT_NOT_RECONCILED",
                    attempt=predecessor.get("attempt"),
                    charged=predecessor.get("charged"),
                    refund=predecessor.get("refund"),
                    credit_classification=predecessor.get("credit_classification"),
                )
            )

        matching_failure_count = sum(
            1
            for row in attempts
            if row.get("failure_family") == predecessor.get("failure_family")
            and row.get("representation") == predecessor.get("representation")
            and row.get("outcome") == "FAILED"
        )
        prompt_changed = candidate.get("prompt_sha256") != predecessor.get("prompt_sha256")
        input_changed = candidate.get("input_sha256") != predecessor.get("input_sha256")
        if not prompt_changed:
            failures.append(_failure("PROMPT_SHA256_NOT_CHANGED"))
        if not input_changed:
            failures.append(_failure("INPUT_SHA256_NOT_CHANGED"))

        strategy = _validate_strategy_change(
            payload.get("candidate", {}).get("strategy_change"),
            predecessor=predecessor,
            candidate=candidate,
            failures=failures,
            required=matching_failure_count >= 2,
        )

    allowed = not failures
    return {
        "schema": OUTPUT_SCHEMA,
        "status": "PASS_PAID_RETRY_ALLOWED" if allowed else "BLOCK_PAID_RETRY",
        "paid_retry_allowed": allowed,
        "scope_id": scope_id.strip() if isinstance(scope_id, str) else None,
        "retry_of_attempt": retry_of_attempt,
        "matching_failure_count_same_family_and_representation": matching_failure_count,
        "predecessor_credit_resolution": credit_resolution,
        "strategy_change": strategy,
        "audit": {
            "attempts": attempts,
            "candidate": {
                **candidate,
                "paid_submission": paid_submission is True,
                "retry_of_attempt": retry_of_attempt,
            },
        },
        "failures": failures,
        "policy": {
            "third_paid_retry_after_two_same_family_and_representation_failures_requires_strategy_change": True,
            "allowed_strategy_changes": sorted(ALLOWED_STRATEGIES),
            "strategy_change_requires_validated_evidence_sha256": True,
            "prompt_sha256_and_input_sha256_must_both_change": True,
            "retry_credit_precondition": "VERIFIED_ZERO_OR_FULL_REFUND",
            "gate_submits_nothing": True,
        },
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit whether one paid retry is admissible.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        result = audit_retry_request(payload)
    except Exception as exc:
        result = {
            "schema": OUTPUT_SCHEMA,
            "status": "BLOCK_PAID_RETRY",
            "paid_retry_allowed": False,
            "failures": [{"code": "INPUT_READ_OR_PARSE_FAILED", "error": str(exc)}],
            "policy": {"gate_submits_nothing": True, "fail_closed": True},
        }

    write_json_atomic(args.out, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["paid_retry_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
