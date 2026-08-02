import concurrent.futures as cf
import json

from backlotos_producer_supervisor.invoker import AgentInvoker
from backlotos_producer_supervisor.ledger import read_ndjson
from backlotos_producer_supervisor.runtime import Runtime


def test_dispatch_idempotent_second_call_deduped(tmp_project):
    calls = []

    def mock_fn(agent, payload):
        calls.append((agent, payload))
        return {"ok": True, "status": "COMPLETE"}

    invoker = AgentInvoker(mock_fn=mock_fn)
    r = Runtime(invoker)
    req = {"verb": "dispatch", "params": {
        "project_path": str(tmp_project), "episode_id": "E001", "stage": "script_generate",
        "payload": {"spec": "same-content"},
    }}
    first = r.dispatch(req)
    second = r.dispatch(req)
    assert first["status"] == "COMPLETED"
    assert first.get("deduped", False) is False
    assert second.get("deduped") is True
    assert second["idempotency_key"] == first["idempotency_key"]
    # the downstream agent must only have been invoked ONCE
    assert len(calls) == 1
    jobs = read_ndjson(tmp_project / "jobs.ndjson")
    assert len(jobs) == 1


def test_dispatch_different_payload_is_not_deduped(tmp_project):
    invoker = AgentInvoker(mock_fn=lambda a, p: {"ok": True, "status": "COMPLETE"})
    r = Runtime(invoker)
    r.dispatch({"verb": "dispatch", "params": {"project_path": str(tmp_project), "episode_id": "E001", "stage": "script_generate", "payload": {"spec": "A"}}})
    second = r.dispatch({"verb": "dispatch", "params": {"project_path": str(tmp_project), "episode_id": "E001", "stage": "script_generate", "payload": {"spec": "B"}}})
    assert second.get("deduped", False) is False
    jobs = read_ndjson(tmp_project / "jobs.ndjson")
    assert len(jobs) == 2


def test_concurrent_dispatch_many_no_ledger_corruption(tmp_project):
    invoker = AgentInvoker(mock_fn=lambda a, p: {"ok": True, "status": "COMPLETE"})
    r = Runtime(invoker, workers=8)
    jobs = [
        {"project_path": str(tmp_project), "episode_id": f"E{n:03d}", "stage": "script_generate", "payload": {"n": n}}
        for n in range(1, 41)
    ]
    result = r.dispatch({"verb": "dispatchMany", "params": {"jobs": jobs}})
    assert result["ok"] is True
    assert result["total"] == 40
    assert result["failed"] == 0

    # ledger integrity: exactly 40 well-formed, parseable lines, no interleaving corruption
    raw_lines = (tmp_project / "jobs.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 40
    parsed = [json.loads(line) for line in raw_lines]
    assert len(parsed) == 40
    keys = {p["idempotency_key"] for p in parsed}
    assert len(keys) == 40  # all distinct, none lost/duplicated


def test_concurrent_dispatch_same_key_dedupes_and_invokes_once():
    calls = []
    invoker = AgentInvoker(mock_fn=lambda a, p: (calls.append(1), {"ok": True, "status": "COMPLETE"})[1])
    r = Runtime(invoker, workers=8)

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        project = Path(td)
        job = {"project_path": str(project), "episode_id": "E001", "stage": "script_generate", "payload": {"same": True}}
        jobs = [dict(job) for _ in range(10)]
        result = r.dispatch({"verb": "dispatchMany", "params": {"jobs": jobs}})
        assert result["ok"] is True
        keys = {r_["idempotency_key"] for r_ in result["results"]}
        assert len(keys) == 1
        # exactly one COMPLETED record on disk and the downstream agent was
        # invoked exactly once despite 10 concurrent dispatch calls for the same key
        assert len(calls) == 1
        jobs_on_disk = read_ndjson(project / "jobs.ndjson")
        assert len(jobs_on_disk) == 1
        assert jobs_on_disk[0]["status"] == "COMPLETED"


def test_dispatch_many_content_failure_is_not_top_level_success(tmp_project):
    invoker = AgentInvoker(mock_fn=lambda a, p: {"ok": False, "status": "FAIL", "issue": "real failure"})
    r = Runtime(invoker)
    result = r.dispatch({"verb": "dispatchMany", "params": {"jobs": [{
        "project_path": str(tmp_project), "episode_id": "E001", "stage": "script_generate", "payload": {},
    }]}})
    assert result["ok"] is False
    assert result["status"] == "FAIL"
    assert result["passed"] == 0
    assert result["failed"] == 1
    assert len(result["failed_items"]) == 1


def test_downstream_inconsistent_ok_true_failure_status_is_failed(tmp_project):
    invoker = AgentInvoker(mock_fn=lambda a, p: {"ok": True, "status": "CAPABILITY_FAIL"})
    result = Runtime(invoker).dispatch({"verb": "dispatch", "params": {
        "project_path": str(tmp_project), "episode_id": "E001", "stage": "script_generate", "payload": {},
    }})
    assert result["ok"] is False
    assert result["status"] == "FAILED"
