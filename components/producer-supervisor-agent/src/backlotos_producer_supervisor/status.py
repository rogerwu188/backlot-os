"""Aggregate REAL on-disk project state -- never a cached/fabricated number."""
from __future__ import annotations

import json
from pathlib import Path

from .ledger import latest_by_key, read_ndjson


def _episode_files_status(project_path: Path) -> list[dict]:
    episodes_dir = project_path / "episodes"
    out = []
    if not episodes_dir.is_dir():
        return out
    for path in sorted(episodes_dir.glob("*.json")):
        with path.open(encoding="utf-8") as stream:
            state = json.load(stream)
        stages = state.get("stages", [])
        complete = sum(1 for s in stages if s.get("status") == "COMPLETE")
        out.append({
            "episode_id": state.get("episode_id", path.stem),
            "source": "episodes_json",
            "stages": stages,
            "complete_stage_count": complete,
            "total_stage_count": len(stages),
        })
    return out


def _plan_jobs_status(project_path: Path) -> list[dict]:
    plan_path = project_path / "plan.json"
    if not plan_path.is_file():
        return []
    with plan_path.open(encoding="utf-8") as stream:
        plan = json.load(stream)
    jobs = read_ndjson(project_path / "jobs.ndjson")
    latest_stage: dict[tuple, dict] = {}
    for job in jobs:
        key = (job.get("episode_id"), job.get("stage"))
        prior = latest_stage.get(key)
        if prior is None or job.get("timestamp", "") >= prior.get("timestamp", ""):
            latest_stage[key] = job
    out = []
    for episode in plan.get("episodes", []):
        eid = episode["episode_id"]
        sequence = episode.get("stage_sequence", [])
        stages = []
        for stage in sequence:
            record = latest_stage.get((eid, stage))
            stages.append({"id": stage, "status": record.get("status") if record else "WAITING"})
        complete = sum(1 for s in stages if s["status"] == "COMPLETED")
        out.append({
            "episode_id": eid, "source": "plan_and_jobs_ledger", "stages": stages,
            "complete_stage_count": complete, "total_stage_count": len(stages),
        })
    return out


def project_status(project_path: str | Path) -> dict:
    project_path = Path(project_path)
    if not project_path.is_dir():
        return {"ok": False, "status": "ERROR", "error": f"project path not found: {project_path}"}
    launcher_episodes = _episode_files_status(project_path)
    producer_episodes = _plan_jobs_status(project_path)
    # Once a producer plan exists its jobs ledger is the authoritative view of
    # the ten-stage producer workflow. Keep the launcher's earlier seven-stage
    # snapshot for observability instead of silently ignoring producer jobs.
    episodes = producer_episodes or launcher_episodes
    total_stages = sum(e["total_stage_count"] for e in episodes)
    complete_stages = sum(e["complete_stage_count"] for e in episodes)
    progress_pct = round(100.0 * complete_stages / total_stages, 2) if total_stages else 0.0
    return {
        "ok": True,
        "status": "REPORTED",
        "project_path": str(project_path),
        "episode_count": len(episodes),
        "episodes": episodes,
        "launcher_episode_snapshot": launcher_episodes if producer_episodes else [],
        "progress_percent": progress_pct,
        "complete_stage_count": complete_stages,
        "total_stage_count": total_stages,
    }
