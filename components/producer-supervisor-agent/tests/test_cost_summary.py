import json

from backlotos_producer_supervisor.ledger import append_ndjson
from backlotos_producer_supervisor.runtime import Runtime


def _credit_event(episode_id, stage, consumed, refunded=0.0, provider="acme", provider_task_id=None, cost_key=None, final=True):
    return {
        "schema": "backlotos.credit-event/1.0",
        "event_id": f"evt-{episode_id}-{stage}-{consumed}-{provider_task_id}",
        "cost_key": cost_key,
        "supersedes_event_id": None,
        "timestamp": "2026-01-01T00:00:00Z",
        "episode_id": episode_id,
        "stage": stage,
        "provider": provider,
        "provider_task_id": provider_task_id,
        "estimated": None,
        "consumed": consumed,
        "refunded": refunded,
        "net": round(consumed - refunded, 6),
        "final": final,
        "evidence_ref": None,
    }


def test_cost_summary_not_reported_when_no_events(tmp_project):
    r = Runtime()
    result = r.dispatch({"verb": "cost-summary", "params": {"project_path": str(tmp_project), "episode_id": "E001"}})
    assert result["ok"] is True
    assert result["status"] == "NOT_REPORTED"
    assert result["consumed"] is None  # never fabricated as 0


def test_cost_summary_net_aggregation(tmp_project):
    ledger = tmp_project / "credits.ndjson"
    append_ndjson(ledger, _credit_event("E001", "media_generation", 10.0, 2.0, cost_key="E001|media_generation|acme|t1"))
    append_ndjson(ledger, _credit_event("E001", "storyboard", 5.0, 0.0, cost_key="E001|storyboard|acme|t2"))
    r = Runtime()
    result = r.dispatch({"verb": "cost-summary", "params": {"project_path": str(tmp_project), "episode_id": "E001"}})
    assert result["consumed"] == 15.0
    assert result["refunded"] == 2.0
    assert result["net"] == 13.0
    assert result["by_stage"]["media_generation"]["net"] == 8.0
    assert result["by_stage"]["script_generate"]["status"] == "NOT_REPORTED" if "script_generate" in result["by_stage"] else True


def test_cost_summary_detects_duplicate_provider_task_id(tmp_project):
    ledger = tmp_project / "credits.ndjson"
    append_ndjson(ledger, _credit_event("E001", "media_generation", 10.0, provider_task_id="dup-1", cost_key="k1"))
    append_ndjson(ledger, _credit_event("E001", "media_generation", 10.0, provider_task_id="dup-1", cost_key="k2"))
    r = Runtime()
    result = r.dispatch({"verb": "cost-summary", "params": {"project_path": str(tmp_project), "episode_id": "E001"}})
    assert "POSSIBLE_DUPLICATE_CHARGE" in result["flags"]
    assert result["possible_duplicate_charges"][0]["provider_task_id"] == "dup-1"
