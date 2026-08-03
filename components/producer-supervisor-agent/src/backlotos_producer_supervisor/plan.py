"""Producer planning: chapter/episode chunking, stage sequence, agent-owner
map, concurrency policy, and retry policy. Structural scaffolding only --
this module never writes prose, dialogue, or shot content; that is the
Story/Storyboard agents' job.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .ledger import atomic_write_json, utc_now

PLAN_SCHEMA = "backlotos.producer-plan/1.0"

STAGE_SEQUENCE = [
    "novel_adaptation",
    "script_generate",
    "script_review",
    "storyboard",
    "media_generation",
    "agentcut_edit",
    "review",
    "repair",
    "final_candidate",
    "human_release_authorization",
]

# Which of the five agents owns each stage.
STAGE_OWNER = {
    "novel_adaptation": "story",
    "script_generate": "story",
    "script_review": "story",
    "storyboard": "pipeline",
    "media_generation": "pipeline",
    "agentcut_edit": "post",
    "review": "review",
    "repair": "post",
    "final_candidate": "review",
    "human_release_authorization": "human",
}


def _chunk_chapters(chapters: list[Any] | None, chapter_count: int | None, episode_count: int) -> list[dict]:
    """Greedy even distribution of chapters across episode_count episodes."""
    if chapters:
        total = len(chapters)
        ids = [c.get("id", index) if isinstance(c, dict) else c for index, c in enumerate(chapters, 1)]
    else:
        total = int(chapter_count or episode_count)
        ids = list(range(1, total + 1))
    episode_count = max(1, int(episode_count))
    base, remainder = divmod(total, episode_count)
    mapping = []
    cursor = 0
    for ep_index in range(1, episode_count + 1):
        size = base + (1 if ep_index <= remainder else 0)
        chunk = ids[cursor:cursor + size]
        cursor += size
        mapping.append({"episode_id": f"E{ep_index:03d}", "chapter_ids": chunk})
    return mapping


def build_plan(
    *,
    episode_count: int,
    chapters: list[Any] | None = None,
    chapter_count: int | None = None,
    episode_duration_seconds: int = 180,
    concurrency: int = 3,
    max_retry_attempts: int = 2,
    project_path: str | None = None,
) -> dict:
    episode_count = int(episode_count)
    if not 1 <= episode_count <= 1000:
        raise ValueError("episode_count must be between 1 and 1000")
    episode_duration_seconds = int(episode_duration_seconds)
    if not 30 <= episode_duration_seconds <= 7200:
        raise ValueError("episode_duration_seconds must be between 30 and 7200")
    concurrency = max(1, int(concurrency))
    chapter_map = _chunk_chapters(chapters, chapter_count, episode_count)
    episodes = []
    for entry in chapter_map:
        episodes.append({
            "episode_id": entry["episode_id"],
            "chapter_ids": entry["chapter_ids"],
            "plot_target": "PLACEHOLDER: filled by Story Agent novel_adaptation stage from source excerpt",
            "end_hook": "PLACEHOLDER: filled by Story Agent; must be a consequential end hook, not an ambience shot",
            "target_duration_sec": episode_duration_seconds,
            "stage_sequence": list(STAGE_SEQUENCE),
            "current_stage": STAGE_SEQUENCE[0],
            "version": 1,
        })
    plan = {
        "schema": PLAN_SCHEMA,
        "generated_at": utc_now(),
        "episode_count": episode_count,
        "stage_sequence": list(STAGE_SEQUENCE),
        "stage_owner": dict(STAGE_OWNER),
        "concurrency_plan": {"max_in_flight_episodes": concurrency, "policy": "episode-isolated; one stage failure pauses only that episode"},
        "retry_policy": {"max_attempts": max(1, int(max_retry_attempts)), "semantics": "failed-only", "escalation": "human review after max_attempts exhausted"},
        "episodes": episodes,
    }
    if project_path:
        atomic_write_json(Path(project_path) / "plan.json", plan)
        plan["persisted_to"] = str(Path(project_path) / "plan.json")
    return plan
