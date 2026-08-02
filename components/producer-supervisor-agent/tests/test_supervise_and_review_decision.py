import hashlib

from backlotos_producer_supervisor.runtime import Runtime


def test_supervise_flags_stale_evidence_by_version():
    r = Runtime()
    evidence = [
        {"ref": "script", "episode_id": "E001", "project_id": "GEN-1", "version": 1, "sha256": "a" * 64, "timestamp": "2026-01-01T00:00:00Z"},
    ]
    result = r.dispatch({"verb": "supervise", "params": {
        "episode_id": "E001", "project_id": "GEN-1", "current_version": 2, "evidence": evidence,
    }})
    assert "STALE_EVIDENCE" in result["flags"]
    assert result["status"] == "FAIL"


def test_supervise_flags_stale_by_timestamp():
    r = Runtime()
    evidence = [{"ref": "shot1", "episode_id": "E001", "timestamp": "2025-01-01T00:00:00Z"}]
    result = r.dispatch({"verb": "supervise", "params": {
        "episode_id": "E001", "evidence": evidence, "latest_accepted_revision_at": "2026-01-01T00:00:00Z",
    }})
    assert "STALE_EVIDENCE" in result["flags"]


def test_supervise_sha_mismatch_detected(tmp_path):
    f = tmp_path / "clip.bin"
    f.write_bytes(b"hello world")
    wrong_sha = hashlib.sha256(b"different content").hexdigest()
    r = Runtime()
    result = r.dispatch({"verb": "supervise", "params": {
        "episode_id": "E001",
        "evidence": [{"ref": "clip", "episode_id": "E001", "sha256": wrong_sha, "local_path": str(f)}],
    }})
    assert result["status"] == "FAIL"
    assert result["checks"]["sha256_integrity"]["malformed"]


def test_supervise_unexecuted_checks_report_not_run_never_pass():
    r = Runtime()
    result = r.dispatch({"verb": "supervise", "params": {"episode_id": "E001", "evidence": [{"ref": "x", "episode_id": "E001"}]}})
    assert result["checks"]["duration_compliance"]["status"] == "NOT_RUN"
    assert result["checks"]["sha256_integrity"]["status"] == "NOT_RUN"


def test_supervise_padding_advisory_only_not_hard_fail():
    r = Runtime()
    evidence = [
        {"ref": "l1", "episode_id": "E001", "text": "The hero walked into the room slowly and looked around."},
        {"ref": "l2", "episode_id": "E001", "text": "The hero walked into the room slowly and looked around."},
    ]
    result = r.dispatch({"verb": "supervise", "params": {"episode_id": "E001", "evidence": evidence}})
    assert "POSSIBLE_PADDING" in result["flags"]
    assert result["status"] == "NOT_RUN"  # other required evidence checks were not executed


def test_supervise_empty_evidence_never_passes():
    result = Runtime().dispatch({"verb": "supervise", "params": {"episode_id": "E001", "evidence": []}})
    assert result["ok"] is False
    assert result["status"] == "NOT_RUN"
    assert result["checks"]["identity_consistency"]["status"] == "NOT_RUN"


def test_duration_does_not_sum_duplicate_final_measurements():
    evidence = [
        {"ref": "render", "episode_id": "E001", "scope": "final", "duration_seconds": 180.0},
        {"ref": "review", "episode_id": "E001", "scope": "final_cut", "duration_seconds": 180.1},
    ]
    result = Runtime().dispatch({"verb": "supervise", "params": {
        "episode_id": "E001", "target_duration_seconds": 180, "evidence": evidence,
    }})
    duration = result["checks"]["duration_compliance"]
    assert duration["status"] == "PASS"
    assert duration["total_duration_seconds"] == 180.1


def test_review_decision_never_downgrades_block():
    r = Runtime()
    report = {"issues": [{"issue_id": "I1", "severity": "BLOCK", "problem": "missing end hook", "blocking": True}]}
    result = r.dispatch({"verb": "review-decision", "params": {
        "review_report": report,
        # attacker-style payload trying to force a pass; must have no effect
        "force_pass": True, "override_decision": "PASS",
    }})
    assert result["decision"] == "BLOCK"
    assert result["structured_revision_requests"]


def test_review_decision_advise_for_nonblocking_and_checklist():
    r = Runtime()
    report = {"issues": [{"issue_id": "I2", "severity": "MINOR", "problem": "pacing slightly slow"}]}
    checklist = {"early_conflict": True, "no_padding_for_duration": False}
    result = r.dispatch({"verb": "review-decision", "params": {"review_report": report, "checklist": checklist}})
    assert result["decision"] == "ADVISE"


def test_review_decision_pass_when_clean():
    r = Runtime()
    result = r.dispatch({"verb": "review-decision", "params": {"review_report": {"issues": []}, "checklist": {k: True for k in [
        "early_conflict", "every_scene_advances", "no_recap_or_filler", "escalating_tension", "consequential_end_hook", "no_padding_for_duration",
    ]}}})
    assert result["decision"] == "PASS"


def test_review_decision_incomplete_checklist_cannot_pass():
    result = Runtime().dispatch({"verb": "review-decision", "params": {"review_report": {"issues": []}}})
    assert result["decision"] == "ADVISE"
    assert result["checklist_not_run"]
