"""Runtime: worker pool (>=4), NDJSON persistent protocol, verb dispatch.

Mirrors claude_story_agent.runtime.Runtime conventions: a VERBS table maps
external verb names (hyphenated or camelCase) to internal methods; every
handler catches CapabilityError and returns a structured CAPABILITY_FAIL,
never a raw traceback; a hard human-authorization boundary is enforced
before any verb executes, and cannot be bypassed by any payload flag.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import threading
from pathlib import Path
from typing import Any

from .cost import cost_summary, project_cost_summary
from .dispatch import dispatch_job, resume_plan, retry_failed
from .intake_validate import validate_intake
from .invoker import AgentInvoker, CapabilityError
from .plan import build_plan
from .review_decision import review_decision as _review_decision
from .status import project_status
from .supervise import supervise_episode
from . import __version__

DEFAULT_WORKERS = 4

# Any verb name, or any params["action"]/params["stage"] value, that implies an
# irreversible platform action requires a real human clicking a real UI/CLI
# confirmation OUTSIDE this package. There is NO bypass: force/confirm/override
# flags in the payload are read and explicitly ignored.
IRREVERSIBLE_VERBS = {
    "publish", "release", "release-episode", "releaseEpisode", "delete",
    "delete-project", "deleteProject", "overwrite-final", "overwriteFinal",
    "platform-upload", "platformUpload", "platform-delete", "platformDelete",
    "human-release-authorization", "humanReleaseAuthorization",
}
IRREVERSIBLE_ACTIONS = {
    "publish", "release", "delete", "overwrite_final", "platform_upload",
    "platform_delete", "human_release_authorization",
}


def _is_irreversible_request(verb: str, params: dict) -> bool:
    if verb in IRREVERSIBLE_VERBS:
        return True
    if str(params.get("action", "")) in IRREVERSIBLE_ACTIONS:
        return True
    if str(params.get("stage", "")) == "human_release_authorization":
        return True
    return False


class Runtime:
    def __init__(self, invoker: AgentInvoker | None = None, workers: int = DEFAULT_WORKERS):
        self.invoker = invoker or AgentInvoker()
        self.workers = max(4, int(workers))  # hard floor of 4
        self._state_lock = threading.Lock()
        self._active_jobs = 0
        self._completed_jobs = 0

    # ---- single verbs ----
    def health(self, _req=None) -> dict:
        with self._state_lock:
            active, completed = self._active_jobs, self._completed_jobs
        return {
            "ok": True, "status": "ready", "version": __version__, "verb": "health", "workers": self.workers,
            "active_jobs": active, "completed_jobs": completed,
            "invoker_mode": self.invoker.mode,
        }

    def validate(self, req: dict) -> dict:
        payload = req.get("intake") or req.get("params", {}).get("intake") or req.get("params") or {}
        result = validate_intake(payload)
        return {"ok": result["ok"], "verb": "validate", **result}

    def plan(self, req: dict) -> dict:
        params = req.get("params", req)
        try:
            project_path = params.get("project_path")
            project_config = {}
            if project_path:
                config_path = Path(project_path) / "project.json"
                if config_path.is_file():
                    project_config = json.loads(config_path.read_text(encoding="utf-8"))
            inputs = project_config.get("inputs", {}) if isinstance(project_config, dict) else {}
            episode_files = list((Path(project_path) / "episodes").glob("*.json")) if project_path and (Path(project_path) / "episodes").is_dir() else []
            episode_count = params.get("episode_count") or params.get("episodeCount") or inputs.get("episode_count") or len(episode_files) or 1
            result = build_plan(
                episode_count=episode_count,
                chapters=params.get("chapters"),
                chapter_count=params.get("chapter_count"),
                episode_duration_seconds=params.get("episode_duration_seconds") or inputs.get("episode_duration_seconds") or 180,
                concurrency=params.get("concurrency", 3),
                max_retry_attempts=params.get("max_retry_attempts", 2),
                project_path=project_path,
            )
            return {"ok": True, "verb": "plan", "plan": result}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "verb": "plan", "status": "ERROR", "error": f"plan failed ({type(exc).__name__})"}

    def dispatch_one(self, req: dict, *, track_active: bool = True) -> dict:
        params = req.get("params", req)
        project_path = params.get("project_path")
        episode_id = params.get("episode_id")
        stage = params.get("stage")
        payload = params.get("payload", {})
        if not project_path or not episode_id or not stage:
            return {"ok": False, "verb": "dispatch", "status": "ERROR", "error": "project_path, episode_id, and stage are required"}
        if track_active:
            with self._state_lock:
                self._active_jobs += 1
        try:
            # Public requests cannot bypass idempotency. Forced redispatch is
            # reserved for the internal failed-only retry path.
            record = dispatch_job(project_path, episode_id, stage, payload, self.invoker, agent=params.get("agent"))
            return {"ok": record.get("status") in ("COMPLETED", "DISPATCHED") or record.get("deduped", False), "verb": "dispatch", **record}
        except CapabilityError as exc:
            return {"ok": False, "verb": "dispatch", "status": "CAPABILITY_FAIL", "error": str(exc)}
        finally:
            if track_active:
                with self._state_lock:
                    self._active_jobs -= 1
                    self._completed_jobs += 1

    def supervise(self, req: dict) -> dict:
        params = req.get("params", req)
        episode_id = params.get("episode_id")
        evidence = params.get("evidence", [])
        if not episode_id:
            return {"ok": False, "verb": "supervise", "status": "ERROR", "error": "episode_id is required"}
        result = supervise_episode(
            episode_id, evidence,
            project_id=params.get("project_id"), current_version=params.get("current_version"),
            latest_accepted_revision_at=params.get("latest_accepted_revision_at"),
            target_duration_seconds=params.get("target_duration_seconds"),
        )
        return {"verb": "supervise", **result}

    def status(self, req: dict) -> dict:
        params = req.get("params", req)
        project_path = params.get("project_path")
        if not project_path:
            return {"ok": False, "verb": "status", "status": "ERROR", "error": "project_path is required"}
        return {"verb": "status", **project_status(project_path)}

    def resume(self, req: dict) -> dict:
        params = req.get("params", req)
        project_path = params.get("project_path")
        if not project_path:
            return {"ok": False, "verb": "resume", "status": "ERROR", "error": "project_path is required"}
        return {"verb": "resume", **resume_plan(project_path)}

    def retry_failed_verb(self, req: dict) -> dict:
        params = req.get("params", req)
        project_path = params.get("project_path")
        if not project_path:
            return {"ok": False, "verb": "retry-failed", "status": "ERROR", "error": "project_path is required"}
        return {"verb": "retry-failed", **retry_failed(project_path, self.invoker)}

    def cost_summary_verb(self, req: dict) -> dict:
        params = req.get("params", req)
        project_path = params.get("project_path")
        if not project_path:
            return {"ok": False, "verb": "cost-summary", "status": "ERROR", "error": "project_path is required"}
        if params.get("episode_id"):
            return {"verb": "cost-summary", **cost_summary(project_path, params["episode_id"])}
        return {"ok": True, "verb": "cost-summary", **project_cost_summary(project_path)}

    def review_decision_verb(self, req: dict) -> dict:
        params = req.get("params", req)
        review_report = params.get("review_report", {})
        checklist = params.get("checklist")
        return {"verb": "review-decision", **_review_decision(review_report, checklist)}

    def blocked_human_authorization(self, req: dict) -> dict:
        verb = req.get("verb") or req.get("method") or "unknown"
        return {
            "ok": False, "verb": verb, "status": "BLOCKED",
            "reason": "HUMAN_AUTHORIZATION_REQUIRED",
            "note": "publish/delete/overwrite-final/irreversible platform actions require a real human confirmation outside this package; no payload flag can bypass this.",
        }

    # ---- batch: concurrent dispatch of many jobs (>=4 workers) ----
    def dispatch_many(self, req: dict) -> dict:
        params = req.get("params", req)
        jobs = params.get("jobs", [])
        results = [None] * len(jobs)
        with self._state_lock:
            self._active_jobs += len(jobs)
        with cf.ThreadPoolExecutor(max_workers=self.workers) as ex:
            futures = {ex.submit(self.dispatch_one, {"params": job}, track_active=False): i for i, job in enumerate(jobs)}
            for fut in cf.as_completed(futures):
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    results[idx] = {"ok": False, "status": "ERROR", "error": str(exc)}
                finally:
                    with self._state_lock:
                        self._active_jobs -= 1
                        self._completed_jobs += 1
        failed_items = [r for r in results if not r.get("ok", False) and not r.get("deduped", False)]
        capability_failed = [r for r in failed_items if r.get("status") in {"CAPABILITY_FAIL", "ADAPTER_REQUIRED"} or r.get("reason") == "CAPABILITY_FAIL"]
        failed = len(failed_items)
        return {
            "ok": failed == 0,
            "status": "PASS" if failed == 0 else ("CAPABILITY_FAIL" if capability_failed else "FAIL"),
            "verb": "dispatchMany",
            "results": results,
            "workers": self.workers,
            "total": len(results),
            "passed": len(results) - failed,
            "failed": failed,
            "failed_items": failed_items,
            "retry_items": [r for r in failed_items if r.get("status") == "FAILED"],
        }

    VERBS = {
        "health": "health",
        "validate": "validate",
        "plan": "plan",
        "dispatch": "dispatch_one",
        "dispatchMany": "dispatch_many",
        "dispatch-many": "dispatch_many",
        "supervise": "supervise",
        "status": "status",
        "progress": "status",
        "resume": "resume",
        "retry-failed": "retry_failed_verb",
        "retryFailed": "retry_failed_verb",
        "cost-summary": "cost_summary_verb",
        "costSummary": "cost_summary_verb",
        "review-decision": "review_decision_verb",
        "reviewDecision": "review_decision_verb",
    }

    def dispatch(self, req: dict) -> dict:
        verb = req.get("verb") or req.get("method")
        params = req.get("params", {}) if isinstance(req.get("params"), dict) else {}
        if _is_irreversible_request(str(verb), params):
            return self.blocked_human_authorization(req)
        meth_name = self.VERBS.get(verb)
        if not meth_name:
            return {"ok": False, "error": f"unknown verb: {verb}", "verbs": sorted(self.VERBS)}
        try:
            return getattr(self, meth_name)(req)
        except CapabilityError as exc:
            return {"ok": False, "verb": verb, "status": "CAPABILITY_FAIL", "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - never leak a raw traceback
            return {"ok": False, "verb": verb, "status": "ERROR", "error": f"request failed ({type(exc).__name__})"}

    # ---- NDJSON persistent loop ----
    def serve_ndjson(self, inp=None, out=None):
        import json
        import sys
        inp = inp or sys.stdin
        out = out or sys.stdout
        for line in inp:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except Exception as exc:  # noqa: BLE001
                out.write(json.dumps({"ok": False, "status": "ERROR", "error": f"bad json ({type(exc).__name__})"}) + "\n")
                out.flush()
                continue
            try:
                rep = self.dispatch(req)
            except Exception as exc:  # noqa: BLE001
                rep = {"ok": False, "status": "ERROR", "error": str(exc), "verb": req.get("verb")}
            out.write(json.dumps(rep, ensure_ascii=False) + "\n")
            out.flush()
