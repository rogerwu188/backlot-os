"""Cost aggregation over credits.ndjson -- mirrors backlotos_launcher.pipeline.credit_summary
disk format exactly (schema backlotos.credit-event/1.0), adding duplicate
provider_task_id detection and honest NOT_REPORTED semantics per stage."""
from __future__ import annotations

from pathlib import Path

from .ledger import read_ndjson


def _reduce(events: list[dict]) -> list[dict]:
    latest_by_key: dict[str, dict] = {}
    unkeyed = []
    for item in events:
        if item.get("cost_key"):
            latest_by_key[item["cost_key"]] = item
        else:
            unkeyed.append(item)
    return unkeyed + list(latest_by_key.values())


def cost_summary(project_path: str | Path, episode_id: str | None = None, stages: list[str] | None = None) -> dict:
    project_path = Path(project_path)
    events = read_ndjson(project_path / "credits.ndjson")
    if episode_id is not None:
        events = [e for e in events if e.get("episode_id") == episode_id]
    effective = _reduce(events)

    consumed = round(sum(float(e.get("consumed", 0)) for e in effective), 6)
    refunded = round(sum(float(e.get("refunded", 0)) for e in effective), 6)
    net = round(consumed - refunded, 6)

    by_stage_effective: dict[str, list[dict]] = {}
    for e in effective:
        by_stage_effective.setdefault(str(e.get("stage", "unknown")), []).append(e)

    stage_costs: dict[str, dict] = {}
    known_stages = set(stages or []) | set(by_stage_effective.keys())
    for stage in known_stages:
        items = by_stage_effective.get(stage, [])
        if not items:
            stage_costs[stage] = {"status": "NOT_REPORTED", "consumed": None, "refunded": None, "net": None}
        else:
            c = round(sum(float(i.get("consumed", 0)) for i in items), 6)
            r = round(sum(float(i.get("refunded", 0)) for i in items), 6)
            stage_costs[stage] = {
                "status": "FINAL" if all(i.get("final") for i in items) else "PROVISIONAL",
                "consumed": c, "refunded": r, "net": round(c - r, 6),
            }

    # duplicate provider_task_id detection: same (provider, provider_task_id) but
    # different cost_key values across the RAW (unreduced) event stream.
    by_task: dict[tuple, set] = {}
    for e in events:
        task_id = e.get("provider_task_id")
        if not task_id:
            continue
        tkey = (e.get("provider", "unknown"), task_id)
        by_task.setdefault(tkey, set()).add(e.get("cost_key"))
    duplicates = [
        {"provider": provider, "provider_task_id": task_id, "distinct_cost_keys": sorted(k for k in keys if k)}
        for (provider, task_id), keys in by_task.items() if len([k for k in keys if k]) > 1
    ]

    return {
        "ok": True,
        "schema": "backlotos.producer-cost-summary/1.0",
        "episode_id": episode_id,
        "status": "FINAL" if effective and all(e.get("final") for e in effective) else ("PROVISIONAL" if effective else "NOT_REPORTED"),
        "event_count": len(events),
        "effective_cost_count": len(effective),
        "consumed": consumed if effective else None,
        "refunded": refunded if effective else None,
        "net": net if effective else None,
        "by_stage": stage_costs,
        "possible_duplicate_charges": duplicates,
        "flags": ["POSSIBLE_DUPLICATE_CHARGE"] if duplicates else [],
    }


def project_cost_summary(project_path: str | Path) -> dict:
    project_path = Path(project_path)
    episodes_dir = project_path / "episodes"
    episode_ids = sorted(p.stem for p in episodes_dir.glob("*.json")) if episodes_dir.is_dir() else []
    per_episode = {eid: cost_summary(project_path, eid) for eid in episode_ids}
    total_summary = cost_summary(project_path, None)
    return {"ok": True, "project_total": total_summary, "per_episode": per_episode}
