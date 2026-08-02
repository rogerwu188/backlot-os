from backlotos_producer_supervisor.pipeline_gates import health, run_gate


def test_pipeline_gate_health_finds_repository_tools(monkeypatch):
    monkeypatch.delenv("BACKLOT_PIPELINE_TOOLS_DIR", raising=False)
    result = health()
    assert result["ok"] is True
    assert result["status"] == "ready"
    assert result["gates"]["anti-padding"] is True


def test_anti_padding_gate_executes_real_pass_and_fail():
    passing = run_gate("anti-padding", {"dialogue_draft": [
        {"dia_id": "D1", "payload": ["new_event"]},
        {"dia_id": "D2", "payload": ["power_shift"]},
    ]})
    failing = run_gate("anti-padding", {"dialogue_draft": [
        {"dia_id": "D1", "payload": []},
        {"dia_id": "D2", "payload": []},
    ]})
    assert passing["ok"] is True
    assert passing["status"] == "PASS"
    assert failing["ok"] is False
    assert failing["status"] == "FAIL"


def test_media_generation_requires_giggle_key(monkeypatch):
    monkeypatch.delenv("GIGGLE_API_KEY", raising=False)
    result = run_gate("media-generation", {})
    assert result["ok"] is False
    assert result["status"] == "ADAPTER_REQUIRED"


def test_media_generation_ready_with_giggle_key(monkeypatch):
    monkeypatch.setenv("GIGGLE_API_KEY", "test-placeholder")
    result = run_gate("media-generation", {})
    assert result["ok"] is True and result["status"] == "PASS"
    assert result["provider"]["defaults"]["image_model"] == "gpt2img"


def test_unknown_pipeline_gate_is_structured_error():
    result = run_gate("does-not-exist", {})
    assert result["ok"] is False
    assert result["status"] == "ERROR"
