import json
import subprocess
import sys
from pathlib import Path

from tools.retry_strategy_change_gate import audit_retry_request


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def failed_attempt(
    attempt,
    *,
    prompt_sha256,
    input_sha256,
    representation="omni_long_take",
    failure_family="ACTION_CAUSALITY",
    charged=0,
    refund=0,
    credit_classification="VERIFIED_ZERO",
):
    return {
        "failure_family": failure_family,
        "representation": representation,
        "prompt_sha256": prompt_sha256,
        "input_sha256": input_sha256,
        "attempt": attempt,
        "charged": charged,
        "refund": refund,
        "credit_classification": credit_classification,
        "outcome": "FAILED",
    }


def request(attempts, *, strategy_change=None, representation="omni_long_take"):
    candidate = {
        "failure_family": "ACTION_CAUSALITY",
        "representation": representation,
        "prompt_sha256": SHA_D,
        "input_sha256": SHA_E,
        "attempt": max(row["attempt"] for row in attempts) + 1,
        "charged": 0,
        "refund": 0,
        "credit_classification": "NOT_SUBMITTED",
        "outcome": "NOT_SUBMITTED",
        "paid_submission": True,
        "retry_of_attempt": max(row["attempt"] for row in attempts),
    }
    if strategy_change is not None:
        candidate["strategy_change"] = strategy_change
    return {
        "schema": "backlotos.retry_strategy_change_request.v1",
        "scope_id": "E40/U18",
        "attempts": attempts,
        "candidate": candidate,
    }


def failure_codes(result):
    return {row["code"] for row in result["failures"]}


def valid_strategy(kind="shot_split", *, to_representation="omni_long_take"):
    return {
        "kind": kind,
        "validated": True,
        "evidence_sha256": SHA_C,
        "from_representation": "omni_long_take",
        "to_representation": to_representation,
    }


def test_first_retry_passes_after_verified_zero_with_changed_hashes():
    payload = request([failed_attempt(1, prompt_sha256=SHA_A, input_sha256=SHA_B)])
    result = audit_retry_request(payload)
    assert result["status"] == "PASS_PAID_RETRY_ALLOWED"
    assert result["predecessor_credit_resolution"] == "VERIFIED_ZERO"
    assert result["matching_failure_count_same_family_and_representation"] == 1


def test_full_refund_satisfies_credit_precondition():
    payload = request(
        [
            failed_attempt(
                1,
                prompt_sha256=SHA_A,
                input_sha256=SHA_B,
                charged=240,
                refund=240,
                credit_classification="CHARGED_THEN_REFUNDED",
            )
        ]
    )
    result = audit_retry_request(payload)
    assert result["status"] == "PASS_PAID_RETRY_ALLOWED"
    assert result["predecessor_credit_resolution"] == "FULL_REFUND"


def test_unreconciled_charge_blocks_retry():
    payload = request(
        [
            failed_attempt(
                1,
                prompt_sha256=SHA_A,
                input_sha256=SHA_B,
                charged=240,
                refund=0,
                credit_classification="CHARGE_PENDING",
            )
        ]
    )
    result = audit_retry_request(payload)
    assert result["status"] == "BLOCK_PAID_RETRY"
    assert "PREDECESSOR_CREDIT_NOT_RECONCILED" in failure_codes(result)


def test_zero_charge_without_verified_zero_blocks_retry():
    payload = request(
        [
            failed_attempt(
                1,
                prompt_sha256=SHA_A,
                input_sha256=SHA_B,
                credit_classification="UNKNOWN",
            )
        ]
    )
    assert "PREDECESSOR_CREDIT_NOT_RECONCILED" in failure_codes(audit_retry_request(payload))


def test_third_attempt_after_two_matching_failures_requires_strategy_change():
    payload = request(
        [
            failed_attempt(1, prompt_sha256=SHA_A, input_sha256=SHA_B),
            failed_attempt(2, prompt_sha256=SHA_B, input_sha256=SHA_C),
        ]
    )
    result = audit_retry_request(payload)
    assert result["matching_failure_count_same_family_and_representation"] == 2
    assert "STRATEGY_CHANGE_REQUIRED_AFTER_TWO_FAILURES" in failure_codes(result)


def test_third_attempt_passes_with_validated_strategy_and_changed_hashes():
    payload = request(
        [
            failed_attempt(1, prompt_sha256=SHA_A, input_sha256=SHA_B),
            failed_attempt(2, prompt_sha256=SHA_B, input_sha256=SHA_C),
        ],
        strategy_change=valid_strategy(),
    )
    result = audit_retry_request(payload)
    assert result["status"] == "PASS_PAID_RETRY_ALLOWED"
    assert result["strategy_change"]["kind"] == "shot_split"
    assert result["audit"]["candidate"]["prompt_sha256"] == SHA_D


def test_strategy_evidence_and_validation_are_fail_closed():
    strategy = valid_strategy()
    strategy["validated"] = False
    strategy["evidence_sha256"] = "not-a-sha"
    payload = request(
        [
            failed_attempt(1, prompt_sha256=SHA_A, input_sha256=SHA_B),
            failed_attempt(2, prompt_sha256=SHA_B, input_sha256=SHA_C),
        ],
        strategy_change=strategy,
    )
    codes = failure_codes(audit_retry_request(payload))
    assert "STRATEGY_CHANGE_NOT_VALIDATED" in codes
    assert "STRATEGY_CHANGE_EVIDENCE_SHA256_INVALID" in codes


def test_prompt_and_input_sha_must_both_change():
    payload = request(
        [
            failed_attempt(1, prompt_sha256=SHA_A, input_sha256=SHA_B),
            failed_attempt(2, prompt_sha256=SHA_B, input_sha256=SHA_C),
        ],
        strategy_change=valid_strategy(),
    )
    payload["candidate"]["prompt_sha256"] = SHA_B
    payload["candidate"]["input_sha256"] = SHA_C
    codes = failure_codes(audit_retry_request(payload))
    assert "PROMPT_SHA256_NOT_CHANGED" in codes
    assert "INPUT_SHA256_NOT_CHANGED" in codes


def test_failure_count_is_scoped_to_same_family_and_representation():
    payload = request(
        [
            failed_attempt(1, prompt_sha256=SHA_A, input_sha256=SHA_B, representation="image_to_video"),
            failed_attempt(2, prompt_sha256=SHA_B, input_sha256=SHA_C),
        ]
    )
    result = audit_retry_request(payload)
    assert result["matching_failure_count_same_family_and_representation"] == 1
    assert result["status"] == "PASS_PAID_RETRY_ALLOWED"


def test_transport_change_must_actually_change_representation():
    payload = request(
        [
            failed_attempt(1, prompt_sha256=SHA_A, input_sha256=SHA_B),
            failed_attempt(2, prompt_sha256=SHA_B, input_sha256=SHA_C),
        ],
        strategy_change=valid_strategy("transport_change"),
    )
    assert "TRANSPORT_CHANGE_MUST_CHANGE_REPRESENTATION" in failure_codes(audit_retry_request(payload))


def test_invalid_sha_and_nonsequential_attempt_fail_closed():
    payload = request([failed_attempt(1, prompt_sha256=SHA_A, input_sha256=SHA_B)])
    payload["candidate"]["input_sha256"] = "bad"
    payload["candidate"]["attempt"] = 7
    codes = failure_codes(audit_retry_request(payload))
    assert "INPUT_SHA256_INVALID" in codes
    assert "CANDIDATE_ATTEMPT_NOT_SEQUENTIAL" in codes


def test_cli_writes_atomic_json_and_returns_blocking_exit_code(tmp_path):
    payload = request(
        [
            failed_attempt(
                1,
                prompt_sha256=SHA_A,
                input_sha256=SHA_B,
                charged=100,
                credit_classification="CHARGE_PENDING",
            )
        ]
    )
    input_path = tmp_path / "request.json"
    output_path = tmp_path / "gate.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "retry_strategy_change_gate.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--input", str(input_path), "--out", str(output_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["status"] == "BLOCK_PAID_RETRY"
    assert json.loads(output_path.read_text(encoding="utf-8"))["paid_retry_allowed"] is False
    assert not list(tmp_path.glob(".gate.json.*.tmp"))


def test_cli_invalid_json_still_writes_fail_closed_report(tmp_path):
    input_path = tmp_path / "broken.json"
    output_path = tmp_path / "gate.json"
    input_path.write_text("{", encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "retry_strategy_change_gate.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--input", str(input_path), "--out", str(output_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert report["status"] == "BLOCK_PAID_RETRY"
    assert report["failures"][0]["code"] == "INPUT_READ_OR_PARSE_FAILED"
