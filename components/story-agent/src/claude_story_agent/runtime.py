"""Runtime: worker pool (>=4), NDJSON persistent protocol, verb dispatch."""
from __future__ import annotations
import json, os, sys, threading, concurrent.futures as cf
from .schemas import Episode
from .story_agent import StoryAgent
from .review_agent import ReviewAgent
from .model_adapter import ModelAdapter, CapabilityError
from .versioning import VersionLedger
from .novel_import import import_novel, split_chapters, plan_series, NovelImportError
from .continuity import ContinuityLedger

DEFAULT_WORKERS = 4

class Runtime:
    def __init__(self, adapter: ModelAdapter | None = None, workers: int = DEFAULT_WORKERS):
        self.adapter = adapter or ModelAdapter()
        self.workers = max(4, int(workers))     # floor of 4
        self.ledger = VersionLedger(os.environ.get("BACKLOT_STORY_LEDGER"))
        self._state_lock=threading.Lock();self._active_jobs=0;self._completed_jobs=0
        self.story = StoryAgent(self.adapter, self.ledger)
        self.review = ReviewAgent()

    # ---- single verbs ----
    def health(self, _req=None) -> dict:
        h = self.adapter.health()
        return {"ok": True, "verb": "health", "model": h, "workers": self.workers,
                "review_deterministic": True}

    def validate(self, req) -> dict:
        try:
            ep = Episode.from_dict(req["episode"])
            return {"ok": True, "verb": "validate", "episode_id": ep.episode_id,
                    "shot_count": sum(len(s.get("shots", [])) for s in ep.scenes),
                    "total_duration_sec": round(ep.total_duration(), 1)}
        except Exception as e:
            return {"ok": False, "verb": "validate", "error": str(e)}

    def review_one(self, req) -> dict:
        ep = Episode.from_dict(req["episode"])
        rep = self.review.review(ep)
        return {"ok": True, "verb": "review", "report": rep,
                "failed_only": self.review.failed_only_targets(rep)}

    def generate_one(self, req) -> dict:
        try:
            ep = self.story.generate(req["spec"])
            return {"ok": True, "verb": "generate", "episode": ep}
        except CapabilityError as e:
            return {"ok": False, "verb": "generate", "status": "CAPABILITY_FAIL", "error": str(e)}

    def revise_one(self, req) -> dict:
        try:
            ep = self.story.revise(req["episode"], req.get("failed_shot_ids", []), req.get("notes", ""))
            return {"ok": True, "verb": "revise", "episode": ep}
        except CapabilityError as e:
            return {"ok": False, "verb": "revise", "status": "CAPABILITY_FAIL", "error": str(e)}

    def import_novel_one(self, req) -> dict:
        try:
            result = import_novel(
                req["text"], int(req["total_episodes"]), float(req["episode_duration_sec"])
            )
            return {"ok": True, "verb": "importNovel", **result}
        except (KeyError, NovelImportError, ValueError, TypeError) as exc:
            return {"ok": False, "verb": "importNovel", "error": str(exc)}

    def plan_series_one(self, req) -> dict:
        try:
            chapters = req.get("chapters") or split_chapters(req["text"])
            plan = plan_series(
                chapters,
                int(req["total_episodes"]),
                float(req["episode_duration_sec"]),
                float(req.get("duration_tolerance_sec", 15.0)),
            )
            return {"ok": True, "verb": "planSeries", "series_plan": plan}
        except (KeyError, NovelImportError, ValueError, TypeError) as exc:
            return {"ok": False, "verb": "planSeries", "error": str(exc)}

    def continuity_check_one(self, req) -> dict:
        try:
            ledger = ContinuityLedger(req.get("ledger_path"))
            episode = Episode.from_dict(req["episode"])
            issues = ledger.check_episode(episode)
            recorded = ledger.record(episode, req.get("end_hook", "")) if req.get("record") else None
            blockers = [issue for issue in issues if issue["severity"] == "blocking"]
            return {
                "ok": True,
                "verb": "continuityCheck",
                "passed": not blockers,
                "issues": issues,
                "blocking_count": len(blockers),
                "recorded": recorded,
            }
        except (KeyError, ValueError, TypeError) as exc:
            return {"ok": False, "verb": "continuityCheck", "error": str(exc)}

    def status(self, _req=None) -> dict:
        with self._state_lock: active=self._active_jobs;completed=self._completed_jobs
        last=None if not self.ledger.records else {k:v for k,v in self.ledger.records[-1].items() if k!="output_snapshot"}
        return {"ok": True, "verb": "status", "records": len(self.ledger.records),
                "active_jobs":active,"completed_jobs":completed,
                "last": last}

    # ---- batch verbs (>=4 workers) ----
    def _map(self, fn, items):
        out = [None] * len(items)
        with self._state_lock: self._active_jobs+=len(items)
        with cf.ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = {ex.submit(fn, it): i for i, it in enumerate(items)}
            for f in cf.as_completed(futs):
                try: out[futs[f]] = f.result()
                except Exception as exc: out[futs[f]]={"ok":False,"status":"ERROR","error":str(exc)}
                finally:
                    with self._state_lock: self._active_jobs-=1;self._completed_jobs+=1
        return out

    def generate_many(self, req) -> dict:
        res = self._map(lambda s: self.generate_one({"spec": s}), req["specs"])
        failed=sum(not x.get("ok",False) for x in res)
        return {"ok": failed==0, "status":"PASS" if failed==0 else "CAPABILITY_FAIL", "verb": "generateMany", "results": res, "workers": self.workers,"total":len(res),"failed":failed}

    def review_many(self, req) -> dict:
        res = self._map(lambda e: self.review_one({"episode": e}), req["episodes"])
        failed=sum((not x.get("ok",False)) or not x.get("report",{}).get("passed",False) for x in res)
        return {"ok": failed==0, "status":"PASS" if failed==0 else "CONTENT_FAIL", "verb": "reviewMany", "results": res, "workers": self.workers,"total":len(res),"failed":failed}

    VERBS = {"health": "health", "validate": "validate", "review": "review_one",
             "generate": "generate_one", "revise": "revise_one", "status": "status",
             "progress": "status", "generateMany": "generate_many", "reviewMany": "review_many",
             "importNovel": "import_novel_one", "planSeries": "plan_series_one",
             "continuityCheck": "continuity_check_one"}

    def dispatch(self, req: dict) -> dict:
        verb = req.get("verb")
        meth = self.VERBS.get(verb)
        if not meth:
            return {"ok": False, "error": f"unknown verb: {verb}",
                    "verbs": sorted(self.VERBS)}
        return getattr(self, meth)(req)

    # ---- NDJSON persistent loop: one JSON request per line -> one JSON reply per line ----
    def serve_ndjson(self, inp=None, out=None):
        inp = inp or sys.stdin; out = out or sys.stdout
        for line in inp:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except Exception as e:
                out.write(json.dumps({"ok": False, "error": f"bad json: {e}"}) + "\n"); out.flush(); continue
            try:
                rep = self.dispatch(req)
            except Exception as e:
                rep = {"ok": False, "error": str(e), "verb": req.get("verb")}
            out.write(json.dumps(rep, ensure_ascii=False) + "\n"); out.flush()
