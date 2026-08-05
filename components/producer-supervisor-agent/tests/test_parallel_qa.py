import threading
import time

from backlotos_producer_supervisor.parallel_qa import run_parallel_qa, write_receipt_atomic


def test_parallel_qa_really_runs_gates_concurrently_and_keeps_input_order():
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def runner(gate, payload):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.04)
        with lock:
            active -= 1
        return {"ok": True, "status": "PASS", "seen": payload["value"]}

    tasks = [
        {"qa_id": "visual", "gate": "visual", "payload": {"value": 1}},
        {"qa_id": "ocr", "gate": "ocr", "payload": {"value": 2}},
        {"qa_id": "dialogue", "gate": "dialogue", "payload": {"value": 3}},
    ]
    result = run_parallel_qa(tasks, workers=3, gate_runner=runner)
    assert result["ok"] is True
    assert result["execution_mode"] == "parallel_fan_out_aggregate_barrier"
    assert maximum_active >= 2
    assert [item["qa_id"] for item in result["results"]] == ["visual", "ocr", "dialogue"]


def test_parallel_qa_failure_does_not_cancel_siblings():
    completed = []

    def runner(gate, _payload):
        completed.append(gate)
        if gate == "identity":
            raise RuntimeError("bad candidate")
        return {"ok": True, "status": "PASS"}

    result = run_parallel_qa([
        {"qa_id": "identity", "gate": "identity"},
        {"qa_id": "action", "gate": "action"},
        {"qa_id": "credits", "gate": "credits"},
    ], gate_runner=runner)
    assert result["ok"] is False
    assert result["failed"] == 1
    assert set(completed) == {"identity", "action", "credits"}
    assert result["required_failures"][0]["qa_id"] == "identity"


def test_parallel_qa_optional_failure_is_advisory():
    result = run_parallel_qa([
        {"qa_id": "required", "gate": "required"},
        {"qa_id": "optional", "gate": "optional", "required": False},
    ], gate_runner=lambda gate, _: {"ok": gate == "required", "status": "PASS" if gate == "required" else "FAIL"})
    assert result["ok"] is True
    assert result["status"] == "PASS_WITH_ADVISORIES"


def test_parallel_qa_rejects_duplicate_ids():
    result = run_parallel_qa([
        {"qa_id": "same", "gate": "visual"},
        {"qa_id": "same", "gate": "ocr"},
    ])
    assert result["ok"] is False
    assert "duplicate qa_id" in result["error"]


def test_parallel_qa_writes_atomic_receipt(tmp_path):
    path = write_receipt_atomic(tmp_path / "qa" / "receipt.json", {"ok": True, "status": "PASS"})
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert '"status": "PASS"' in path.read_text(encoding="utf-8")
