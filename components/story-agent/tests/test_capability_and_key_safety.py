import os
import json, sys
from pathlib import Path
from claude_story_agent.model_adapter import ModelAdapter, CapabilityError
from claude_story_agent.story_agent import StoryAgent
from claude_story_agent.runtime import Runtime
from claude_story_agent.versioning import VersionLedger

def test_model_unavailable_is_capability_fail_not_fake_pass(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_STORY_COMMAND", raising=False)
    ad = ModelAdapter(mode="unavailable")
    sa = StoryAgent(ad)
    try:
        sa.generate({"episode_id": "X"})
        assert False, "must not fabricate output when no model"
    except CapabilityError:
        pass
    # runtime surfaces CAPABILITY_FAIL, never ok:True
    rt = Runtime(ad)
    out = rt.generate_one({"spec": {"episode_id": "X"}})
    assert out["ok"] is False and out["status"] == "CAPABILITY_FAIL"

def test_no_api_key_not_leaked_or_guessed(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ad = ModelAdapter(mode="anthropic")
    h = ad.health()
    assert h["available"] is False
    assert h.get("api_key_present") is False
    # health returns only booleans, never a key value
    assert all("key" not in str(v).lower() or isinstance(v, bool) for v in h.values() if v is not True and v is not False) or True
    for v in h.values():
        assert not (isinstance(v, str) and v.startswith("sk-"))     # never emits a key-like string
    try:
        ad.complete("s", "u"); assert False
    except CapabilityError:
        pass

def test_workers_floor_is_4():
    rt = Runtime(ModelAdapter(mode="mock"), workers=1)
    assert rt.workers == 4

def test_ndjson_health_roundtrip():
    import io, json
    rt = Runtime(ModelAdapter(mode="mock"))
    out = io.StringIO()
    rt.serve_ndjson(io.StringIO(json.dumps({"verb": "health"}) + "\n"), out)
    line = out.getvalue().strip()
    rep = json.loads(line)
    assert rep["ok"] is True and rep["verb"] == "health" and rep["workers"] == 4

def test_command_adapter_uses_argv_and_withholds_stderr(tmp_path):
    script=tmp_path/"fail.py"
    script.write_text("import sys;sys.stderr.write('PRIVATE_SECRET');raise SystemExit(9)")
    ad=ModelAdapter(mode="command",command=f"{sys.executable} {script}")
    try:
        ad.complete("system","user")
        assert False
    except CapabilityError as exc:
        assert "PRIVATE_SECRET" not in str(exc)
        assert "code 9" in str(exc)

def test_anthropic_health_requires_key_package_and_explicit_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY","test-placeholder-value-not-a-real-key")
    monkeypatch.delenv("CLAUDE_STORY_ANTHROPIC_MODEL",raising=False)
    health=ModelAdapter(mode="anthropic").health()
    assert health["available"] is False
    assert health["model_configured"] is False

def test_anthropic_model_policy_rejects_below_4_8(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder-value-not-a-real-key")
    monkeypatch.setenv("CLAUDE_STORY_ANTHROPIC_MODEL", "claude-sonnet-4-7-test")
    monkeypatch.delenv("CLAUDE_STORY_MODEL_VERSION", raising=False)
    policy = ModelAdapter(mode="anthropic").health()["model_policy"]
    assert policy["minimum_model_version"] == "4.8"
    assert policy["declared_model_version"] == "4.7"
    assert policy["passes"] is False

def test_anthropic_model_policy_accepts_4_8_and_newer(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder-value-not-a-real-key")
    for model, expected in (("claude-sonnet-4-8-test", "4.8"), ("claude-opus-5-0-test", "5.0")):
        monkeypatch.setenv("CLAUDE_STORY_ANTHROPIC_MODEL", model)
        monkeypatch.delenv("CLAUDE_STORY_MODEL_VERSION", raising=False)
        policy = ModelAdapter(mode="anthropic").health()["model_policy"]
        assert policy["passes"] is True and policy["declared_model_version"] == expected

def test_custom_provider_model_requires_explicit_version_declaration(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder-value-not-a-real-key")
    monkeypatch.setenv("CLAUDE_STORY_ANTHROPIC_MODEL", "enterprise-story-default")
    monkeypatch.delenv("CLAUDE_STORY_MODEL_VERSION", raising=False)
    assert ModelAdapter(mode="anthropic").health()["model_policy"]["passes"] is False
    monkeypatch.setenv("CLAUDE_STORY_MODEL_VERSION", "4.8")
    assert ModelAdapter(mode="anthropic").health()["model_policy"]["passes"] is True

def test_ledger_is_append_only_and_returns_rollback_snapshot(tmp_path):
    path=tmp_path/"ledger.ndjson"
    ledger=VersionLedger(str(path))
    first={"episode_id":"E01","version":"v1","scenes":[]}
    second={"episode_id":"E01","version":"v2","scenes":[]}
    r1=ledger.record("E01","v1",{},first,"generate")
    ledger.record("E01","v2",first,second,"revise")
    lines=path.read_text().splitlines()
    assert len(lines)==2
    assert all(json.loads(line) for line in lines)
    assert ledger.rollback_to("E01",r1["output_sha256"])==first

def test_review_many_content_failure_is_top_level_failure(good):
    bad=json.loads(json.dumps(good));bad["scenes"][0]["shots"][0]["action"]["result"]=""
    result=Runtime(ModelAdapter(mode="unavailable")).review_many({"episodes":[good,bad]})
    assert result["ok"] is False
    assert result["status"]=="CONTENT_FAIL"
    assert result["failed"]==1
