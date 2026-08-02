"""Story Agent — generation + failed-only revision. Requires a model backend.

If no model backend is available, generate/revise raise CapabilityError so the
runtime returns CAPABILITY_FAIL. We never fabricate a script.
"""
from __future__ import annotations
import json, os
from .schemas import Episode, SchemaError
from .model_adapter import ModelAdapter, CapabilityError
from .versioning import VersionLedger

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "prompts")

def _load_prompt(name: str) -> str:
    p = os.path.join(_PROMPT_DIR, name)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < 0:
        raise CapabilityError("model output contained no JSON object")
    return json.loads(text[a:b + 1])

class StoryAgent:
    def __init__(self, adapter: ModelAdapter | None = None, ledger: VersionLedger | None = None):
        self.adapter = adapter or ModelAdapter()
        self.ledger = ledger or VersionLedger()

    def generate(self, spec: dict) -> dict:
        """spec: {episode_id, target_duration_sec, canon, prev_episode, brief, requirements}.
        Returns structured Episode dict. Raises CapabilityError if no model."""
        system = _load_prompt("story_generate.md") or "Generate a structured short-drama episode as strict JSON."
        user = json.dumps(spec, ensure_ascii=False)
        raw = self.adapter.complete(system, user)     # CapabilityError propagates
        try: ep = _extract_json(raw)
        except (json.JSONDecodeError,TypeError,ValueError) as exc:
            raise CapabilityError(f"model output was not valid JSON ({type(exc).__name__})")
        ep.setdefault("episode_id", spec.get("episode_id", "E00"))
        ep.setdefault("version", "v1")
        try:
            Episode.from_dict(ep)
        except (KeyError, TypeError, ValueError) as exc:
            raise CapabilityError(f"model output failed episode contract: {exc}")
        self.ledger.record(ep["episode_id"], ep["version"], spec, ep, "generate")
        return ep

    def revise(self, episode: dict, failed_shot_ids: list, notes: str = "") -> dict:
        """Failed-only revision: only the named shots are regenerated; others kept
        byte-identical. Requires a model. Raises CapabilityError if no model."""
        if not failed_shot_ids:
            return episode
        system = _load_prompt("story_revise.md") or "Revise ONLY the listed shots; return the full episode JSON with others unchanged."
        payload = {"episode": episode, "revise_shot_ids": failed_shot_ids, "notes": notes}
        raw = self.adapter.complete(system, json.dumps(payload, ensure_ascii=False))
        try: revised = _extract_json(raw)
        except (json.JSONDecodeError,TypeError,ValueError) as exc:
            raise CapabilityError(f"revised model output was not valid JSON ({type(exc).__name__})")
        # Enforce the same scene/shot topology. A model may change only the
        # contents of targeted shots; deleting/reordering siblings is rejected.
        keep = set(failed_shot_ids)
        input_scene_ids=[sc.get("scene_id") for sc in episode.get("scenes", [])]
        revised_scene_ids=[sc.get("scene_id") for sc in revised.get("scenes", [])]
        if input_scene_ids != revised_scene_ids:
            raise CapabilityError("failed-only revision changed scene topology")
        in_shots = {sh["shot_id"]: sh for sc in episode.get("scenes", []) for sh in sc.get("shots", [])}
        in_order=[sh["shot_id"] for sc in episode.get("scenes", []) for sh in sc.get("shots", [])]
        out_order=[sh.get("shot_id") for sc in revised.get("scenes", []) for sh in sc.get("shots", [])]
        if in_order != out_order:
            raise CapabilityError("failed-only revision deleted, added, or reordered shots")
        if not keep.issubset(in_shots):
            raise CapabilityError("failed-only target contains an unknown shot_id")
        for sc in revised.get("scenes", []):
            for k, sh in enumerate(sc.get("shots", [])):
                if sh.get("shot_id") not in keep and sh.get("shot_id") in in_shots:
                    sc["shots"][k] = in_shots[sh["shot_id"]]   # restore original
        try:
            Episode.from_dict(revised)
        except (KeyError, TypeError, ValueError) as exc:
            raise CapabilityError(f"revised output failed episode contract: {exc}")
        revised["version"] = _bump(episode.get("version", "v1"))
        self.ledger.record(revised.get("episode_id", episode.get("episode_id")),
                           revised["version"], {"episode": episode, "failed": failed_shot_ids},
                           revised, "revise_failed_only")
        return revised

def _bump(v: str) -> str:
    try:
        return "v" + str(int(v.lstrip("v")) + 1)
    except Exception:
        return v + "+1"
