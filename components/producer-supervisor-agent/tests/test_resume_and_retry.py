from backlotos_producer_supervisor.invoker import AgentInvoker
from backlotos_producer_supervisor.ledger import read_ndjson
from backlotos_producer_supervisor.runtime import Runtime


def _plan(r, project, episode_count=1):
    return r.dispatch({"verb": "plan", "params": {"episode_count": episode_count, "chapter_count": episode_count, "project_path": str(project)}})


def test_resume_after_interrupted_run(tmp_path):
    project = tmp_path / "GEN-INTERRUPTED"
    project.mkdir()
    invoker = AgentInvoker(mock_fn=lambda a, p: {"ok": True, "status": "COMPLETE"})
    r = Runtime(invoker)
    plan_result = _plan(r, project)
    assert plan_result["ok"] is True
    sequence = plan_result["plan"]["episodes"][0]["stage_sequence"]

    # simulate a partial run: complete only the first two stages, then "crash"
    r.dispatch({"verb": "dispatch", "params": {"project_path": str(project), "episode_id": "E001", "stage": sequence[0], "payload": {}}})
    r.dispatch({"verb": "dispatch", "params": {"project_path": str(project), "episode_id": "E001", "stage": sequence[1], "payload": {}}})

    resumed = r.dispatch({"verb": "resume", "params": {"project_path": str(project)}})
    assert resumed["ok"] is True
    next_action = resumed["next_actions"][0]
    assert next_action["episode_id"] == "E001"
    assert next_action["next_stage"] == sequence[2]
    assert next_action["completed_stages"] == sequence[:2]


def test_resume_all_complete_returns_none_next(tmp_path):
    project = tmp_path / "GEN-DONE"
    project.mkdir()
    invoker = AgentInvoker(mock_fn=lambda a, p: {"ok": True, "status": "COMPLETE"})
    r = Runtime(invoker)
    plan_result = _plan(r, project)
    sequence = plan_result["plan"]["episodes"][0]["stage_sequence"]
    non_human_stages = [s for s in sequence if s != "human_release_authorization"]
    for stage in non_human_stages:
        r.dispatch({"verb": "dispatch", "params": {"project_path": str(project), "episode_id": "E001", "stage": stage, "payload": {}}})
    resumed = r.dispatch({"verb": "resume", "params": {"project_path": str(project)}})
    next_action = resumed["next_actions"][0]
    assert next_action["next_stage"] == "human_release_authorization"


def test_retry_failed_only_touches_failed_jobs(tmp_path):
    project = tmp_path / "GEN-RETRY"
    project.mkdir()
    outcomes = {"script_generate": False, "storyboard": True}

    def mock_fn(agent, payload):
        stage = payload.get("__stage_marker__")
        return {"ok": outcomes.get(stage, True), "status": "COMPLETE" if outcomes.get(stage, True) else "AGENT_FAILED"}

    invoker = AgentInvoker(mock_fn=mock_fn)
    r = Runtime(invoker)
    r.dispatch({"verb": "dispatch", "params": {"project_path": str(project), "episode_id": "E001", "stage": "script_generate", "payload": {"__stage_marker__": "script_generate"}}})
    r.dispatch({"verb": "dispatch", "params": {"project_path": str(project), "episode_id": "E001", "stage": "storyboard", "payload": {"__stage_marker__": "storyboard"}}})

    before = read_ndjson(project / "jobs.ndjson")
    completed_before = [j for j in before if j["status"] == "COMPLETED"]
    assert len(completed_before) == 1

    # now let script_generate succeed on retry
    outcomes["script_generate"] = True
    result = r.dispatch({"verb": "retry-failed", "params": {"project_path": str(project)}})
    assert result["ok"] is True
    assert result["retried_count"] == 1
    assert result["retried"][0]["stage"] == "script_generate"
    assert result["retried"][0]["status"] == "COMPLETED"

    after = read_ndjson(project / "jobs.ndjson")
    # the storyboard COMPLETED record must be untouched (still exactly one entry for it)
    storyboard_entries = [j for j in after if j["stage"] == "storyboard"]
    assert len(storyboard_entries) == 1
    script_entries = [j for j in after if j["stage"] == "script_generate"]
    assert len(script_entries) == 2  # original FAILED + the retry COMPLETED


def test_status_reconciles_producer_jobs_over_launcher_snapshot(tmp_project):
    invoker = AgentInvoker(mock_fn=lambda a, p: {"ok": True, "status": "COMPLETE"})
    runtime = Runtime(invoker)
    runtime.dispatch({"verb": "plan", "params": {
        "project_path": str(tmp_project), "episode_count": 2, "chapter_count": 2,
    }})
    runtime.dispatch({"verb": "dispatch", "params": {
        "project_path": str(tmp_project), "episode_id": "E001", "stage": "novel_adaptation", "payload": {},
    }})
    result = runtime.dispatch({"verb": "status", "params": {"project_path": str(tmp_project)}})
    assert result["ok"] is True
    assert result["episodes"][0]["source"] == "plan_and_jobs_ledger"
    assert result["episodes"][0]["complete_stage_count"] == 1
    assert result["launcher_episode_snapshot"]
