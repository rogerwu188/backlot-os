"""Novel import, series continuity, and source-level dialogue pacing."""
import pytest

from claude_story_agent.continuity import ContinuityLedger
from claude_story_agent.model_adapter import ModelAdapter
from claude_story_agent.novel_import import (
    NovelImportError,
    extract_beats,
    import_novel,
    plan_series,
    split_chapters,
)
from claude_story_agent.review_agent import ReviewAgent
from claude_story_agent.runtime import Runtime
from claude_story_agent.schemas import Episode

NOVEL_CN = "\n".join(
    f"第{i}章 试炼\n" + ("少年握剑冲入雨幕。他发现门后藏着假账。" * 30) + "\n「你到底是谁」他问。"
    for i in range(1, 9)
)

GENERIC_BRIEF = {
    "character_id": "A",
    "source_locator": "runtime source paragraph 1",
    "era": "unspecified historical era",
    "region": "unspecified region",
    "age": "adult",
    "gender_presentation": "unspecified",
    "social_role": "protagonist",
    "wardrobe": "plain dark fitted robe, narrow sleeves, worn cloth shoes",
    "face": "oval face, straight brows",
    "hair": "tied hair with plain cord",
    "body": "medium height, lean build",
    "voice": "measured mid-register voice",
    "design_distinction_from": ["No sibling character in this minimal fixture"],
    "narrative_similarity_exception": None,
    "writer_completed_before_asset_generation": True,
}


def episode(dialogue_shots, extra_shots=(), scene_overrides=None):
    scene = {
        "scene_id": "S1",
        "location": "hall",
        "time": "night",
        "weather": "clear",
        "shots": list(dialogue_shots) + list(extra_shots),
    }
    scene.update(scene_overrides or {})
    return {
        "episode_id": "E01",
        "target_duration_sec": 60,
        "duration_tolerance_sec": 60,
        "new_info": ["a", "b", "c", "d", "e", "f"],
        "character_asset_briefs": [GENERIC_BRIEF],
        "scenes": [scene],
    }


def shot(shot_id, duration=6, dialogue=(), **overrides):
    value = {
        "shot_id": shot_id,
        "duration_sec": duration,
        "first_frame_motion_state": f"mid-action {shot_id}",
        "ambient_life": "wind",
        "composition": f"comp-{shot_id}",
        "new_info": [f"info-{shot_id}"],
        "dialogue": [{"speaker": "A", "text": text} for text in dialogue],
    }
    value.update(overrides)
    return value


def test_split_extract_and_plan_exact_totals():
    chapters = split_chapters(NOVEL_CN)
    assert len(chapters) == 8
    assert extract_beats(chapters[0])["beat_count"] > 0
    for count in (1, 3, 8):
        plan = plan_series(chapters, count, 150)
        assert len(plan["episodes"]) == count
        assert plan["pacing_policy"] == "backlotos.us-premium-streaming/1.1"
        covered = sorted({chapter for item in plan["episodes"] for chapter in item["source_chapters"]})
        assert covered[0] == 1 and covered[-1] == 8


def test_split_chapters_fallback_and_refuse_filler():
    chapters = split_chapters("para one\n\n" + "x" * 2500 + "\n\n" + "y" * 2500)
    assert len(chapters) >= 2 and chapters[0]["title"] == "segment-1"
    with pytest.raises(NovelImportError):
        plan_series(split_chapters(NOVEL_CN), 73, 150)


def test_import_novel_runtime_verb_and_no_persistence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = import_novel(NOVEL_CN, 4, 150)
    assert result["series_plan"]["total_episodes"] == 4
    assert list(tmp_path.iterdir()) == []
    runtime_result = Runtime(ModelAdapter(mode="mock")).dispatch({
        "verb": "importNovel",
        "text": NOVEL_CN,
        "total_episodes": 4,
        "episode_duration_sec": 150,
    })
    assert runtime_result["ok"] and runtime_result["chapter_count"] == 8


def test_continuity_reproof_regression_weather_and_hook(tmp_path):
    path = str(tmp_path / "continuity.ndjson")
    ledger = ContinuityLedger(path)
    first_data = episode([shot("A1", dialogue=["hello"])])
    first_data["canon"] = {"audience_known": ["older fact"]}
    ledger.record(Episode.from_dict(first_data), end_hook="the forged ledger surfaces")
    second_data = episode([shot("B1")])
    second_data["episode_id"] = "E02"
    second_data["new_info"] = ["a", "z1", "z2", "z3", "z4", "z5"]
    second_data["canon"] = {"audience_known": ["some other fact"]}
    issues = ContinuityLedger(path).check_episode(Episode.from_dict(second_data))
    checks = {item["check"] for item in issues}
    assert {"CONTINUITY_REPROOF", "CONTINUITY_REGRESSION", "CONTINUITY_WEATHER", "CONTINUITY_HOOK_DROP"} <= checks


def test_continuity_runtime_records_append_only(tmp_path):
    output = Runtime(ModelAdapter(mode="mock")).dispatch({
        "verb": "continuityCheck",
        "episode": episode([shot("A1")]),
        "ledger_path": str(tmp_path / "ledger.ndjson"),
        "record": True,
        "end_hook": "hook",
    })
    assert output["ok"] and output["recorded"]["episode_id"] == "E01"


def test_dialogue_ratio_and_pure_run_gates_block():
    heavy = ["这句台词非常长一直在解释信息" for _ in range(3)]
    ratio_report = ReviewAgent().review(Episode.from_dict(episode([
        shot("A1", duration=6, dialogue=heavy),
        shot("A2", duration=6, dialogue=heavy),
    ])))
    assert any(item["check"] == "DIALOGUE_RATIO" for item in ratio_report["issues"])
    talky = [shot(f"T{i}", duration=5, dialogue=["我们继续说话谈论过去的事情"], new_info=[]) for i in range(3)]
    run_report = ReviewAgent().review(Episode.from_dict(episode(talky)))
    assert any(item["check"] == "DIALOGUE_RUN_TOO_LONG" for item in run_report["issues"])


def test_action_dialogue_ratio_and_visual_restatement_block():
    fights = [
        shot("F1", duration=5, dialogue=["站住别跑我们有话要慢慢讲清楚"], action={"intent": "stop", "force": "ice", "contact": "wrist", "result": "locked"}),
        shot("F2", duration=5, dialogue=["你给我把话说完再走不许逃避"], action={"intent": "hold", "force": "grip", "contact": "arm", "result": "pinned"}),
    ]
    action_report = ReviewAgent().review(Episode.from_dict(episode(fights)))
    assert any(item["check"] == "ACTION_SCENE_DIALOGUE_RATIO" for item in action_report["issues"])
    visual = shot("V1", duration=8, new_info=["冰霜显出账上暗流去向断绝"])
    visual["dialogue"] = [{"speaker": "A", "text": "冰霜显出账上暗流去向断绝"}]
    visual_report = ReviewAgent().review(Episode.from_dict(episode([visual])))
    assert any(item["check"] == "VISUAL_RESTATEMENT" for item in visual_report["issues"])


def test_clean_episode_stays_under_new_dialogue_limits():
    clean = [
        shot("C1", duration=8, dialogue=["何人所为"], action={"intent": "probe", "force": "frost", "contact": "page", "result": "hidden flow revealed"}),
        shot("C2", duration=8, dialogue=["查库"]),
    ]
    report = ReviewAgent().review(Episode.from_dict(episode(clean)))
    blocked_checks = {item["check"] for item in report["issues"]}
    assert not {"DIALOGUE_RATIO", "DIALOGUE_RUN_TOO_LONG", "ACTION_SCENE_DIALOGUE_RATIO", "VISUAL_RESTATEMENT"} & blocked_checks
    assert report["pacing"]["dialogue_time_ratio"] <= 0.35
