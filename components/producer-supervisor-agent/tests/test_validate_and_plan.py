from backlotos_producer_supervisor.runtime import Runtime


def test_validate_good_intake(good_intake):
    r = Runtime()
    result = r.dispatch({"verb": "validate", "intake": good_intake})
    assert result["ok"] is True
    assert result["errors"] == []


def test_validate_bad_intake():
    r = Runtime()
    result = r.dispatch({"verb": "validate", "intake": {"production_type": "not_a_type"}})
    assert result["ok"] is False
    fields = {e["field"] for e in result["errors"]}
    assert "source" in fields or "production_type" in fields


def test_validate_rejects_ambiguous_or_non_http_source(good_intake):
    both = {**good_intake, "source": {"url": "https://books.test/a", "upload": "a.pdf"}}
    assert Runtime().dispatch({"verb": "validate", "intake": both})["ok"] is False
    bad_url = {**good_intake, "source": {"url": "file:///etc/passwd"}}
    assert Runtime().dispatch({"verb": "validate", "intake": bad_url})["ok"] is False


def test_plan_inline_multi_episode(good_intake):
    r = Runtime()
    result = r.dispatch({"verb": "plan", "params": {
        "episode_count": 5, "chapter_count": 12, "episode_duration_seconds": 150,
    }})
    assert result["ok"] is True
    plan = result["plan"]
    assert len(plan["episodes"]) == 5
    total_chapters = sum(len(e["chapter_ids"]) for e in plan["episodes"])
    assert total_chapters == 12
    for episode in plan["episodes"]:
        assert episode["stage_sequence"][0] == "novel_adaptation"
        assert episode["stage_sequence"][-1] == "human_release_authorization"


def test_plan_persists_to_real_project(tmp_project):
    r = Runtime()
    result = r.dispatch({"verb": "plan", "params": {
        "episode_count": 2, "chapters": [{"id": "ch1"}, {"id": "ch2"}, {"id": "ch3"}],
        "project_path": str(tmp_project),
    }})
    assert result["ok"] is True
    assert (tmp_project / "plan.json").is_file()


def test_plan_uses_existing_project_episode_count_and_duration(tmp_project):
    (tmp_project / "project.json").write_text('{"inputs":{"episode_count":7,"episode_duration_seconds":240}}')
    result = Runtime().dispatch({"verb": "plan", "params": {"project_path": str(tmp_project)}})
    assert result["ok"] is True
    assert len(result["plan"]["episodes"]) == 7
    assert result["plan"]["episodes"][0]["target_duration_sec"] == 240
