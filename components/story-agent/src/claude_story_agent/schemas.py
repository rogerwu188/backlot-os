"""Structured episode schema (generic, project-agnostic)."""
from __future__ import annotations
import json, hashlib
from dataclasses import dataclass, field, asdict
from typing import Any

class SchemaError(ValueError):
    """Raised when structured model output is not a usable episode contract."""

def _required_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{path} must be a non-empty string")
    return value

def validate_episode_structure(d: Any) -> None:
    if not isinstance(d, dict):
        raise SchemaError("episode must be an object")
    _required_text(d.get("episode_id"), "episode_id")
    scenes=d.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise SchemaError("scenes must be a non-empty array")
    seen=set()
    for si, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise SchemaError(f"scenes[{si}] must be an object")
        for key in ("scene_id", "location", "time", "weather"):
            _required_text(scene.get(key), f"scenes[{si}].{key}")
        shots=scene.get("shots")
        if not isinstance(shots, list) or not shots:
            raise SchemaError(f"scenes[{si}].shots must be a non-empty array")
        for sj, shot in enumerate(shots):
            path=f"scenes[{si}].shots[{sj}]"
            if not isinstance(shot, dict):
                raise SchemaError(f"{path} must be an object")
            sid=_required_text(shot.get("shot_id"), f"{path}.shot_id")
            if sid in seen: raise SchemaError(f"duplicate shot_id: {sid}")
            seen.add(sid)
            duration=shot.get("duration_sec")
            if isinstance(duration, bool) or not isinstance(duration, (int,float)) or duration <= 0:
                raise SchemaError(f"{path}.duration_sec must be a positive number")
            if shot.get("importance", "normal") not in {"normal", "key"}:
                raise SchemaError(f"{path}.importance must be normal or key")
            if not isinstance(shot.get("action", {}), dict):
                raise SchemaError(f"{path}.action must be an object")
            dialogue=shot.get("dialogue", [])
            if not isinstance(dialogue, list):
                raise SchemaError(f"{path}.dialogue must be an array")
            for di, line in enumerate(dialogue):
                if not isinstance(line, dict):
                    raise SchemaError(f"{path}.dialogue[{di}] must be an object")
                _required_text(line.get("speaker"), f"{path}.dialogue[{di}].speaker")
                _required_text(line.get("text"), f"{path}.dialogue[{di}].text")

def sha256_of(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

DURATION_MIN = 4.0    # per-shot seconds, hard floor
DURATION_MAX = 15.0   # per-shot seconds, hard ceiling

@dataclass
class Dialogue:
    speaker: str
    text: str
    subtext: str = ""
    max_chars: int = 25

@dataclass
class Action:
    intent: str = ""
    force: str = ""
    contact: str = ""
    result: str = ""          # missing result => blocking (action w/o consequence)

@dataclass
class Shot:
    shot_id: str
    duration_sec: float
    importance: str = "normal"          # "key" | "normal"
    action: dict = field(default_factory=dict)   # Action-shaped; {} for non-action
    dialogue: list = field(default_factory=list)
    first_frame_motion_state: str = "" # CL2X-670 analog: mid-action, off-balance start
    ambient_life: str = ""             # CL2X-674 analog: background life; "" allowed only if static_ok
    static_ok: bool = False            # deliberate-static shot (密室独处) exempts ambient_life
    composition: str = ""              # for visual-repeat detection
    new_info: list = field(default_factory=list)

@dataclass
class Scene:
    scene_id: str
    location: str
    time: str
    weather: str
    visual_zone: str = ""
    shots: list = field(default_factory=list)

@dataclass
class Episode:
    episode_id: str
    version: str = "v1"
    target_duration_sec: float = 150.0
    duration_tolerance_sec: float = 15.0
    canon: dict = field(default_factory=dict)     # {characters:{id:{...}}, timeline:[], audience_known:[]}
    prev_episode: dict = field(default_factory=dict)  # {episode_id, last_weather, audience_known}
    scenes: list = field(default_factory=list)
    new_info: list = field(default_factory=list)  # episode-level net-new info items
    mainline_beats: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Episode":
        validate_episode_structure(d)
        return Episode(
            episode_id=d["episode_id"], version=d.get("version", "v1"),
            target_duration_sec=d.get("target_duration_sec", 150.0),
            duration_tolerance_sec=d.get("duration_tolerance_sec", 15.0),
            canon=d.get("canon", {}), prev_episode=d.get("prev_episode", {}),
            scenes=d.get("scenes", []), new_info=d.get("new_info", []),
            mainline_beats=d.get("mainline_beats", []),
        )

    def total_duration(self) -> float:
        return sum(float(sh.get("duration_sec", 0))
                   for sc in self.scenes for sh in sc.get("shots", []))

    def all_shots(self):
        for sc in self.scenes:
            for sh in sc.get("shots", []):
                yield sc, sh
