"""Version + input/output SHA + rollback log (generic, no secrets)."""
from __future__ import annotations
import json, time, os
from .schemas import sha256_of

class VersionLedger:
    def __init__(self, path: str | None = None):
        self.path = path
        self.records: list = []
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as stream:
                for line in stream:
                    try: self.records.append(json.loads(line))
                    except json.JSONDecodeError: continue

    def record(self, episode_id, version, input_obj, output_obj, action):
        rec = {
            "episode_id": episode_id, "version": version, "action": action,
            "input_sha256": sha256_of(input_obj),
            "output_sha256": sha256_of(output_obj),
            "output_snapshot": output_obj,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self.records.append(rec)
        if self.path:
            parent=os.path.dirname(os.path.abspath(self.path));os.makedirs(parent,exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(rec,ensure_ascii=False,sort_keys=True)+"\n")
                stream.flush();os.fsync(stream.fileno())
        return rec

    def rollback_to(self, episode_id, output_sha256):
        """Return the recorded snapshot matching a prior output SHA (or None).
        Non-destructive: never deletes; only reports the target to restore."""
        for rec in reversed(self.records):
            if rec["episode_id"] == episode_id and rec["output_sha256"] == output_sha256:
                return rec.get("output_snapshot")
        return None
