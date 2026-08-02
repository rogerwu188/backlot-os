import json, copy
import pytest
from claude_story_agent.model_adapter import ModelAdapter
from claude_story_agent.story_agent import StoryAgent
from claude_story_agent.review_agent import ReviewAgent
from claude_story_agent.schemas import Episode

def _mock_adapter(episode):
    ad = ModelAdapter(mode="mock")
    ad.set_mock(lambda system, user: json.dumps(episode, ensure_ascii=False))
    return ad

def test_normal_generation(good):
    ad = _mock_adapter(good)
    sa = StoryAgent(ad)
    out = sa.generate({"episode_id": "GEN-01", "target_duration_sec": 30})
    assert out["episode_id"] == "GEN-01"
    assert sum(len(s["shots"]) for s in out["scenes"]) == 5
    assert sa.ledger.records[-1]["action"] == "generate"
    assert len(sa.ledger.records[-1]["output_sha256"]) == 64

def test_failed_only_revision_preserves_others(good):
    # model returns an episode where EVERY shot text changed; agent must restore non-targeted
    mutated = copy.deepcopy(good)
    for sc in mutated["scenes"]:
        for sh in sc["shots"]:
            sh["composition"] = sh["composition"] + "-CHANGED"
    ad = _mock_adapter(mutated)
    sa = StoryAgent(ad)
    revised = sa.revise(copy.deepcopy(good), failed_shot_ids=["s3"])
    shots = {sh["shot_id"]: sh for sc in revised["scenes"] for sh in sc["shots"]}
    assert shots["s3"]["composition"].endswith("-CHANGED")     # target regenerated
    assert shots["s1"]["composition"] == "wide-crowd"          # others preserved byte-identical
    assert revised["version"] == "v2"

def test_review_feeds_failed_only(good):
    good["scenes"][0]["shots"][0]["action"]["result"] = ""     # s1 blocking
    r = ReviewAgent().review(Episode.from_dict(good))
    targets = ReviewAgent().failed_only_targets(r)
    assert "s1" in targets

def test_generation_rejects_malformed_nested_contract(good):
    malformed=copy.deepcopy(good)
    del malformed["scenes"][0]["shots"][0]["duration_sec"]
    sa=StoryAgent(_mock_adapter(malformed))
    with pytest.raises(Exception,match="failed episode contract"):
        sa.generate({"episode_id":"GEN-BAD"})

def test_failed_only_rejects_deleted_sibling(good):
    malformed=copy.deepcopy(good)
    malformed["scenes"][0]["shots"].pop(0)
    sa=StoryAgent(_mock_adapter(malformed))
    with pytest.raises(Exception,match="deleted, added, or reordered"):
        sa.revise(copy.deepcopy(good),failed_shot_ids=["s3"])
