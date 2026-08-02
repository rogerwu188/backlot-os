from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from claude_story_agent.model_adapter import ModelAdapter
from claude_story_agent.runtime import Runtime

from .intake import ImportedSource
from .models import IntakeError, ProjectOptions

PIPELINE_VERSION = "backlotos.pipeline/1.0"
_WRITE_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    latin = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if latin:
        return latin[:48]
    return "story-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def _atomic_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".partial")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _event(project: Path, event: str, data: dict | None = None) -> None:
    record = {"timestamp": _utc_now(), "event": event, "data": data or {}}
    ledger = project / "events.ndjson"
    with _WRITE_LOCK, ledger.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def record_credit(
    project: Path,
    episode_id: str,
    stage: str,
    consumed: float,
    refunded: float = 0.0,
    estimated: float | None = None,
    provider: str = "unknown",
    provider_task_id: str | None = None,
    evidence_ref: str | None = None,
    final: bool = True,
) -> dict:
    project = Path(project).expanduser().resolve()
    episode_path = project / "episodes" / f"{episode_id}.json"
    if not episode_path.is_file():
        raise IntakeError(f"unknown episode: {episode_id}")
    if consumed < 0 or refunded < 0 or (estimated is not None and estimated < 0):
        raise IntakeError("credit values cannot be negative")
    if refunded > consumed:
        raise IntakeError("refunded credits cannot exceed consumed credits")
    timestamp = _utc_now()
    cost_key = f"{episode_id}|{stage}|{provider}|{provider_task_id}" if provider_task_id else None
    existing_events = []
    ledger = project / "credits.ndjson"
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                existing_events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    previous = next((item for item in reversed(existing_events) if cost_key and item.get("cost_key") == cost_key), None)
    identity = f"{cost_key}|{estimated}|{consumed}|{refunded}|{final}|{evidence_ref}" if cost_key else f"{episode_id}|{stage}|{provider}|{timestamp}"
    event_id = hashlib.sha256(identity.encode()).hexdigest()[:20]
    duplicate = next((item for item in existing_events if item.get("event_id") == event_id), None)
    if duplicate:
        return duplicate
    event = {
        "schema": "backlotos.credit-event/1.0",
        "event_id": event_id,
        "cost_key": cost_key,
        "supersedes_event_id": previous.get("event_id") if previous else None,
        "timestamp": timestamp,
        "episode_id": episode_id,
        "stage": stage,
        "provider": provider,
        "provider_task_id": provider_task_id,
        "estimated": estimated,
        "consumed": float(consumed),
        "refunded": float(refunded),
        "net": round(float(consumed) - float(refunded), 6),
        "final": bool(final),
        "evidence_ref": evidence_ref,
    }
    with _WRITE_LOCK, ledger.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return event


def credit_summary(project: Path, episode_id: str | None = None) -> dict:
    project = Path(project).expanduser().resolve()
    ledger = project / "credits.ndjson"
    events = []
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if episode_id is None or item.get("episode_id") == episode_id:
                events.append(item)
    latest_by_key = {}
    unkeyed = []
    for item in events:
        if item.get("cost_key"):
            latest_by_key[item["cost_key"]] = item
        else:
            unkeyed.append(item)
    effective_events = unkeyed + list(latest_by_key.values())
    consumed = round(sum(float(item.get("consumed", 0)) for item in effective_events), 6)
    refunded = round(sum(float(item.get("refunded", 0)) for item in effective_events), 6)
    by_stage: dict[str, float] = {}
    for item in effective_events:
        stage = str(item.get("stage", "unknown"))
        by_stage[stage] = round(by_stage.get(stage, 0) + float(item.get("net", 0)), 6)
    return {
        "schema": "backlotos.credit-summary/1.0",
        "episode_id": episode_id,
        "status": "FINAL" if effective_events and all(item.get("final") for item in effective_events) else ("PROVISIONAL" if effective_events else "NOT_REPORTED"),
        "event_count": len(events),
        "effective_cost_count": len(effective_events),
        "consumed": consumed,
        "refunded": refunded,
        "net": round(consumed - refunded, 6),
        "by_stage": by_stage,
    }


def _split_text(text: str, count: int) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text]
    buckets = [""] * count
    target = max(1, len(text) / count)
    index = 0
    for paragraph in paragraphs:
        if index < count - 1 and buckets[index] and len(buckets[index]) + len(paragraph) > target:
            index += 1
        buckets[index] = (buckets[index] + "\n\n" + paragraph).strip()
    return buckets


def _density(text_length: int, options: ProjectOptions) -> dict:
    total_minutes = options.episode_count * options.episode_duration_seconds / 60
    chars_per_minute = round(text_length / max(total_minutes, 1), 1)
    if chars_per_minute < 80:
        status, message = "WARN", "原文内容相对目标总时长偏少，存在节奏注水风险；系统不会自动补空镜凑时长。"
    elif chars_per_minute > 900:
        status, message = "WARN", "原文内容相对目标总时长偏多，改编需要较高压缩率。"
    else:
        status, message = "PASS", "原文内容密度处于可规划范围。"
    return {"status": status, "characters_per_minute": chars_per_minute, "message": message}


def create_project(source: ImportedSource, options: ProjectOptions, projects_root: Path | None = None) -> Path:
    options.validate()
    root = Path(projects_root or os.environ.get("BACKLOT_PROJECTS_DIR", Path.home() / "BacklotOS" / "projects")).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    project = root / f"{_slug(source.title)}-{stamp}-{source.raw_sha256[:8]}"
    if project.exists():
        raise IntakeError("an identical project was created in the same second")
    for directory in ("source", "story/specs", "story/episodes", "jobs/story", "episodes", "evidence", "logs"):
        (project / directory).mkdir(parents=True, exist_ok=True)
    raw_name = "original" + source.suffix
    (project / "source" / raw_name).write_bytes(source.raw_bytes)
    page_provenance = []
    if source.pages:
        raw_pages = project / "source" / "raw_pages"
        raw_pages.mkdir(parents=True, exist_ok=True)
        for number, page in enumerate(source.pages, 1):
            suffix = ".html" if page.get("media_type") == "text/html" else ".bin"
            stored = raw_pages / f"page-{number:04d}{suffix}"
            stored.write_bytes(page["raw"])
            page_provenance.append({"index": number, "url": page["url"], "media_type": page["media_type"], "sha256": page["sha256"], "stored_path": str(stored.relative_to(project))})
    (project / "source" / "normalized.txt").write_text(source.text + "\n", encoding="utf-8")

    source_complete = not source.crawl or source.crawl.get("status") == "PASS"
    config = {
        "schema": "backlotos.project/1.0",
        "pipeline_version": PIPELINE_VERSION,
        "project_id": project.name,
        "title": source.title,
        "created_at": _utc_now(),
        "inputs": options.to_dict(),
        "story_policy": {
            "policy_version": "backlotos.us-premium-streaming/1.0",
            "immediate_conflict": True,
            "filler_allowed": False,
            "recap_dialogue_allowed": False,
            "padding_allowed": False,
            "opening_hook_required": True,
            "mid_episode_escalation_required": True,
            "end_hook_required": True
        },
        "release": {"automatic_publish": False, "status": "NOT_AUTHORIZED"},
    }
    provenance = {
        "schema": "backlotos.source-provenance/1.0",
        "source_name": source.source_name,
        "source_uri": source.source_uri,
        "media_type": source.media_type,
        "stored_path": f"source/{raw_name}",
        "raw_sha256": source.raw_sha256,
        "normalized_text_sha256": source.text_sha256,
        "normalized_character_count": len(source.text),
        "page_count": len(source.pages) if source.pages else 1,
        "pages": page_provenance,
        "crawl": source.crawl,
    }
    excerpts = _split_text(source.text, options.episode_count)
    specs = []
    for number, excerpt in enumerate(excerpts, 1):
        episode_id = f"E{number:03d}"
        spec = {
            "schema": "backlotos.story-spec/1.0",
            "episode_id": episode_id,
            "target_duration_sec": options.episode_duration_seconds,
            "production_type": options.production_type,
            "aspect_ratio": options.aspect_ratio,
            "visual_format": options.visual_format,
            "source": {
                "normalized_text_sha256": source.text_sha256,
                "excerpt": excerpt,
                "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            },
            "requirements": [
                "Remain faithful to the supplied source excerpt.",
                "Do not add padding solely to reach runtime.",
                "Use US premium-streaming pacing: immediate conflict, compressed dialogue, escalation, and a consequential end hook.",
                "Remove greetings, recap, repeated facts, procedural filler, and details that do not change the story.",
                f"Write visual direction for {options.visual_format}; keep that visual format consistent across the project.",
                "Return the structured BacklotOS episode contract.",
            ],
        }
        specs.append(spec)
        _atomic_json(project / "story" / "specs" / f"{episode_id}.json", spec)
        _atomic_json(project / "jobs" / "story" / f"{episode_id}.json", {
            "schema": "backlotos.job/1.0", "job_id": f"story-{episode_id}", "stage": "story_generation",
            "episode_id": episode_id, "status": "QUEUED" if source_complete else "BLOCKED_SOURCE_PARTIAL", "attempts": 0,
            "credits": {"status": "NOT_REPORTED", "estimated": None, "consumed": None, "refunded": None, "net": None},
        })
        _atomic_json(project / "episodes" / f"{episode_id}.json", {
            "schema": "backlotos.episode-state/1.0",
            "episode_id": episode_id,
            "updated_at": _utc_now(),
            "stages": [
                {"id": "source_plan", "status": "COMPLETE"},
                {"id": "story_generation", "status": "QUEUED" if source_complete else "BLOCKED_SOURCE_PARTIAL"},
                {"id": "story_review", "status": "WAITING"},
                {"id": "visual_planning", "status": "WAITING"},
                {"id": "media_generation", "status": "WAITING"},
                {"id": "editing", "status": "WAITING"},
                {"id": "review", "status": "WAITING"}
            ]
        })
    _atomic_json(project / "project.json", config)
    _atomic_json(project / "source" / "provenance.json", provenance)
    _atomic_json(project / "story" / "episode_plan.json", {
        "schema": "backlotos.episode-plan/1.0",
        "episode_count": options.episode_count,
        "episode_duration_seconds": options.episode_duration_seconds,
        "total_target_duration_seconds": options.episode_count * options.episode_duration_seconds,
        "density": _density(len(source.text), options),
        "episodes": [{"episode_id": item["episode_id"], "excerpt_sha256": item["source"]["excerpt_sha256"]} for item in specs],
    })
    _atomic_json(project / "pipeline.json", {
        "schema": "backlotos.pipeline-state/1.0",
        "status": "STARTED" if source_complete else "SOURCE_PARTIAL",
        "updated_at": _utc_now(),
        "stages": [
            {"id": "source_import", "status": "COMPLETE" if source_complete else "PARTIAL"},
            {"id": "story_generation", "status": "QUEUED" if source_complete else "BLOCKED_SOURCE_PARTIAL", "total": options.episode_count, "complete": 0, "failed": 0},
            {"id": "story_review", "status": "WAITING_FOR_STORY"},
            {"id": "visual_planning", "status": "WAITING_FOR_STORY"},
            {"id": "media_generation", "status": "WAITING_FOR_VISUAL_PLAN"},
            {"id": "editing", "status": "WAITING_FOR_MEDIA"},
            {"id": "final_review", "status": "WAITING_FOR_EDIT"},
            {"id": "release", "status": "HUMAN_ONLY"},
        ],
    })
    _event(project, "PROJECT_CREATED", {"episodes": options.episode_count, "source_sha256": source.raw_sha256})
    return project


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def status(project: Path) -> dict:
    project = Path(project).expanduser().resolve()
    if not (project / "project.json").is_file():
        raise IntakeError("project.json was not found")
    return {
        "project": _load_json(project / "project.json"),
        "pipeline": _load_json(project / "pipeline.json"),
        "episode_plan": _load_json(project / "story" / "episode_plan.json"),
        "credits": credit_summary(project),
    }


def run_story_stage(project: Path, workers: int = 4) -> dict:
    project = Path(project).expanduser().resolve()
    state = status(project)
    adapter = ModelAdapter()
    health = adapter.health()
    pipeline = state["pipeline"]
    provenance = _load_json(project / "source" / "provenance.json")
    if provenance.get("crawl") and provenance["crawl"].get("status") != "PASS":
        return {"ok": False, "status": "BLOCKED_SOURCE_PARTIAL", "project_path": str(project), "crawl": provenance["crawl"]}
    story_stage = next(stage for stage in pipeline["stages"] if stage["id"] == "story_generation")
    if not health.get("available"):
        story_stage["status"] = "WAITING_FOR_MODEL"
        pipeline["status"] = "WAITING_FOR_MODEL"
        pipeline["updated_at"] = _utc_now()
        _atomic_json(project / "pipeline.json", pipeline)
        _event(project, "STORY_WAITING_FOR_MODEL", {"model": health})
        return {"ok": False, "status": "WAITING_FOR_MODEL", "project_path": str(project), "model": health}

    queued = []
    for job_path in sorted((project / "jobs" / "story").glob("*.json")):
        job = _load_json(job_path)
        if job.get("status") in {"QUEUED", "RETRY"}:
            queued.append((job_path, job, _load_json(project / "story" / "specs" / f"{job['episode_id']}.json")))
    if not queued:
        return {"ok": True, "status": "COMPLETE", "project_path": str(project), "generated": 0}
    story_stage["status"] = "RUNNING"
    pipeline["status"] = "RUNNING"
    pipeline["updated_at"] = _utc_now()
    _atomic_json(project / "pipeline.json", pipeline)
    runtime = Runtime(adapter, workers=max(4, workers))
    result = runtime.generate_many({"specs": [item[2] for item in queued]})
    generated = failed = 0
    for (job_path, job, _spec), item_result in zip(queued, result["results"]):
        episode_state_path = project / "episodes" / f"{job['episode_id']}.json"
        episode_state = _load_json(episode_state_path)
        episode_story_stage = next(stage for stage in episode_state["stages"] if stage["id"] == "story_generation")
        job["attempts"] = int(job.get("attempts", 0)) + 1
        if item_result.get("ok"):
            episode = item_result["episode"]
            _atomic_json(project / "story" / "episodes" / f"{job['episode_id']}.json", episode)
            job["status"] = "COMPLETE"
            episode_story_stage["status"] = "COMPLETE"
            next(stage for stage in episode_state["stages"] if stage["id"] == "story_review")["status"] = "QUEUED"
            job["output_sha256"] = hashlib.sha256(json.dumps(episode, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            generated += 1
        else:
            job["status"] = "CAPABILITY_FAIL" if item_result.get("status") == "CAPABILITY_FAIL" else "ERROR"
            episode_story_stage["status"] = job["status"]
            job["error"] = item_result.get("error", "story generation failed")
            failed += 1
        _atomic_json(job_path, job)
        episode_state["updated_at"] = _utc_now()
        _atomic_json(episode_state_path, episode_state)
    all_jobs = [_load_json(path) for path in sorted((project / "jobs" / "story").glob("*.json"))]
    complete_total = sum(job.get("status") == "COMPLETE" for job in all_jobs)
    failed_total = sum(job.get("status") in {"CAPABILITY_FAIL", "ERROR"} for job in all_jobs)
    story_stage.update({"complete": complete_total, "failed": failed_total})
    story_stage["status"] = "COMPLETE" if complete_total == len(all_jobs) else "ATTENTION_REQUIRED"
    pipeline["status"] = "STORY_COMPLETE" if complete_total == len(all_jobs) else "ATTENTION_REQUIRED"
    if complete_total == len(all_jobs):
        next(stage for stage in pipeline["stages"] if stage["id"] == "story_review")["status"] = "QUEUED"
    pipeline["updated_at"] = _utc_now()
    _atomic_json(project / "pipeline.json", pipeline)
    _event(project, "STORY_BATCH_FINISHED", {"generated": generated, "failed": failed})
    return {"ok": failed == 0, "status": story_stage["status"], "project_path": str(project), "generated": generated, "failed": failed}


def start_in_background(project: Path, workers: int = 4) -> threading.Thread:
    thread = threading.Thread(target=run_story_stage, args=(project, workers), name=f"backlotos-{Path(project).name}", daemon=True)
    thread.start()
    return thread
