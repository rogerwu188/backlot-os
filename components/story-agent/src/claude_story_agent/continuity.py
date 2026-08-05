"""Deterministic, append-only series continuity ledger."""
from __future__ import annotations

import json
import os
import re

from .schemas import Episode, sha256_of


def _norm(value: str) -> str:
    return re.sub(r"[^\w一-鿿]+", "", str(value).lower())


class ContinuityLedger:
    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("BACKLOT_STORY_CONTINUITY", "")
        self.records: list[dict] = []
        if self.path and os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as stream:
                for line in stream:
                    if line.strip():
                        self.records.append(json.loads(line))

    def known_facts(self) -> set[str]:
        facts: set[str] = set()
        for record in self.records:
            facts.update(map(_norm, record.get("facts") or []))
        return facts

    def last(self) -> dict:
        return self.records[-1] if self.records else {}

    def check_episode(self, episode: Episode) -> list[dict]:
        issues: list[dict] = []
        known = self.known_facts()
        previous = self.last()
        for info in episode.new_info:
            if _norm(info) in known:
                issues.append({
                    "check": "CONTINUITY_REPROOF",
                    "severity": "blocking",
                    "location": episode.episode_id,
                    "message": f"new_info re-proves a fact the audience already knows: {str(info)[:40]}",
                    "fix": "cut it or replace it with genuinely new mainline information",
                })
        declared = set(map(_norm, episode.canon.get("audience_known") or []))
        if declared and known and not known.issubset(declared):
            issues.append({
                "check": "CONTINUITY_REGRESSION",
                "severity": "blocking",
                "location": episode.episode_id,
                "message": "episode canon.audience_known dropped facts recorded in the ledger",
                "fix": "carry the full audience-known list forward; knowledge never regresses",
            })
        previous_weather = _norm(previous.get("end_state", {}).get("weather", ""))
        if previous_weather:
            weathers = [
                _norm(scene.get("weather", ""))
                for scene in episode.scenes
                if scene.get("weather")
            ]
            if (
                weathers
                and all(weather == previous_weather for weather in weathers)
                and not episode.canon.get("weather_source_mandate")
            ):
                issues.append({
                    "check": "CONTINUITY_WEATHER",
                    "severity": "warning",
                    "location": episode.episode_id,
                    "message": "entire episode repeats previous weather with no source mandate",
                    "fix": "vary weather or declare canon.weather_source_mandate",
                })
        hook = previous.get("end_hook", "")
        if hook:
            hook_norm = _norm(hook)
            corpus = [_norm(value) for value in episode.new_info]
            corpus.extend(_norm(value) for value in episode.mainline_beats)
            picked_up = any(
                (hook_norm[:12] and hook_norm[:12] in value)
                or (len(value) >= 6 and value in hook_norm)
                for value in corpus
            )
            if not picked_up:
                issues.append({
                    "check": "CONTINUITY_HOOK_DROP",
                    "severity": "warning",
                    "location": episode.episode_id,
                    "message": "previous episode's end hook is never addressed",
                    "fix": "advance the promised hook before introducing new threads",
                })
        return issues

    def record(self, episode: Episode, end_hook: str = "") -> dict:
        last_scene = episode.scenes[-1] if episode.scenes else {}
        record = {
            "episode_id": episode.episode_id,
            "version": episode.version,
            "facts": [str(value) for value in episode.new_info],
            "end_state": {
                "weather": last_scene.get("weather", ""),
                "time": last_scene.get("time", ""),
                "location": last_scene.get("location", ""),
            },
            "end_hook": end_hook,
            "episode_sha256": sha256_of(episode.to_dict()),
        }
        self.records.append(record)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
