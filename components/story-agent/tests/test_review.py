import copy
from claude_story_agent.schemas import Episode
from claude_story_agent.review_agent import ReviewAgent

R = ReviewAgent()

def rep(d): return R.review(Episode.from_dict(d))

def test_good_episode_passes(good):
    r = rep(good)
    assert r["passed"] is True, r["issues"]
    assert r["blocking_count"] == 0

def test_canon_conflict_fails(good):
    good["scenes"][0]["shots"][0]["dialogue"] = [{"speaker": "Stranger", "text": "hi", "subtext": "x"}]
    r = rep(good)
    assert r["passed"] is False
    assert any(i["check"] == "CANON_UNKNOWN_CHARACTER" and i["severity"] == "blocking" for i in r["issues"])

def test_repeat_explanation_fails(good):
    good["new_info"] = ["dup", "dup", "ni3", "ni4", "ni5", "ni6"]
    r = rep(good)
    assert r["passed"] is False
    assert any(i["check"] == "REPEAT_EXPLANATION" for i in r["issues"])

def test_duration_mismatch_fails(good):
    good["target_duration_sec"] = 200   # 30s total now far below target
    r = rep(good)
    assert r["passed"] is False
    assert any(i["check"] == "EPISODE_DURATION" for i in r["issues"])

def test_visual_repeat_fails(good):
    good["scenes"][0]["shots"][1]["composition"] = "wide-crowd"  # dup of s1
    r = rep(good)
    assert r["passed"] is False
    assert any(i["check"] == "VISUAL_REPEAT" for i in r["issues"])

def test_action_missing_result_fails(good):
    good["scenes"][0]["shots"][0]["action"]["result"] = ""
    r = rep(good)
    assert r["passed"] is False
    assert any(i["check"] == "ACTION_NO_RESULT" and i["severity"] == "blocking" for i in r["issues"])

def test_key_shot_below_4_fails(good):
    # s1 is key; give it penalty 2 (long dialogue + missing ambient) -> score 3 < 4
    good["scenes"][0]["shots"][0]["ambient_life"] = ""
    good["scenes"][0]["shots"][0]["dialogue"] = [{"speaker": "Hero", "text": "x"*40, "subtext": "y"}]
    r = rep(good)
    assert r["shot_scores"]["s1"] == 3
    assert r["passed"] is False
    assert any(f["shot_id"] == "s1" for f in r["failed_shots"])

def test_normal_shot_score_3_passes(good):
    # s2 is normal; penalty 2 -> score 3 == threshold -> not failed, episode still passes (warnings only)
    good["scenes"][0]["shots"][1]["ambient_life"] = ""
    good["scenes"][0]["shots"][1]["dialogue"] = [{"speaker": "Ally", "text": "x"*40, "subtext": "y"}]
    r = rep(good)
    assert r["shot_scores"]["s2"] == 3
    assert not any(f["shot_id"] == "s2" for f in r["failed_shots"])
    assert r["passed"] is True

def test_stable_issue_id(good):
    good["scenes"][0]["shots"][0]["action"]["result"] = ""
    a = rep(copy.deepcopy(good)); b = rep(copy.deepcopy(good))
    ida = [i["issue_id"] for i in a["issues"] if i["check"] == "ACTION_NO_RESULT"][0]
    idb = [i["issue_id"] for i in b["issues"] if i["check"] == "ACTION_NO_RESULT"][0]
    assert ida == idb  # deterministic/stable

def test_repeated_dialogue_is_blocking_filler(good):
    good["scenes"][0]["shots"][1]["dialogue"] = [{"speaker": "Ally", "text": "not yet", "subtext": "buying time"}]
    r = rep(good)
    assert r["passed"] is False
    assert any(i["check"] == "DIALOGUE_REPEAT" and i["blocking"] for i in r["issues"])

def test_non_advancing_shot_is_reported(good):
    shot = good["scenes"][0]["shots"][1]
    shot["new_info"] = []
    shot["action"] = {}
    r = rep(good)
    assert any(i["check"] == "SHOT_NO_STORY_ADVANCE" for i in r["issues"])
    assert r["pacing"]["advancing_shot_ratio"] == 0.8

def test_opening_hook_is_hard_gate(good):
    shot = good["scenes"][0]["shots"][0]
    shot["new_info"] = []
    shot["action"] = {}
    shot["dialogue"] = [{"speaker": "Hero", "text": "hello", "subtext": ""}]
    r = rep(good)
    assert r["passed"] is False
    assert r["pacing"]["opening_hook"] is False
    assert any(i["check"] == "OPENING_HOOK_MISSING" for i in r["issues"])

def test_end_hook_is_hard_gate(good):
    shot = good["scenes"][0]["shots"][-1]
    shot["new_info"] = []
    shot["action"] = {}
    r = rep(good)
    assert r["passed"] is False
    assert r["pacing"]["end_hook"] is False
    assert any(i["check"] == "END_HOOK_MISSING" for i in r["issues"])

def test_pacing_policy_and_metrics_are_reported(good):
    r = rep(good)
    assert r["pacing"]["policy_version"] == "backlotos.us-premium-streaming/1.0"
    assert r["pacing"]["opening_hook"] is True
    assert r["pacing"]["end_hook"] is True
    assert r["pacing"]["advancing_shot_ratio"] == 1.0
