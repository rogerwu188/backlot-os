"""Script Review Agent — deterministic, decoupled from generation."""
from __future__ import annotations
import hashlib
from .schemas import Episode, DURATION_MIN, DURATION_MAX

KEY_PASS = 4
NORMAL_PASS = 3
MIN_NEW_INFO = 6
MIN_EVENTS_PER_MIN = 4.0
DIALOGUE_MAX_CHARS = 25
RULE_VERSION = "backlotos.story-review.v1"

def _iid(check: str, loc: str) -> str:
    return "ISS-" + hashlib.sha1(f"{check}|{loc}".encode()).hexdigest()[:10]

def _issue(check, severity, loc, message, fix):
    return {"issue_id": _iid(check, loc), "check": check, "rule_id": check,
            "rule_version": RULE_VERSION, "severity": severity,
            "blocking": severity == "blocking", "confidence": 1.0,
            "location": loc, "message": message, "fix": fix,
            "recommendation": fix,
            "decision": {"state": "machine", "rollback_allowed": True}}

class ReviewAgent:
    """All checks are pure functions of the structured Episode."""

    def review(self, ep: Episode) -> dict:
        issues: list = []
        shot_scores: dict = {}
        shot_penalty: dict = {}

        canon_chars = set((ep.canon.get("characters") or {}).keys())
        known = set(map(str, ep.canon.get("audience_known") or []))
        prev_weather = (ep.prev_episode or {}).get("last_weather")
        seen_compositions: dict = {}
        seen_explanations: dict = {}

        def penal(shot_id, n):
            shot_penalty[shot_id] = shot_penalty.get(shot_id, 0) + n

        # ---- episode-level: duration ----
        total = ep.total_duration()
        lo = ep.target_duration_sec - ep.duration_tolerance_sec
        hi = ep.target_duration_sec + ep.duration_tolerance_sec
        if not (lo <= total <= hi):
            issues.append(_issue("EPISODE_DURATION", "blocking", ep.episode_id,
                f"total {total:.0f}s outside target {ep.target_duration_sec:.0f}±{ep.duration_tolerance_sec:.0f}s",
                "adjust shot durations to hit target; do not pad with static/slow-mo"))

        # ---- episode-level: new-info density ----
        ni = [str(x) for x in ep.new_info]
        if len(set(ni)) < MIN_NEW_INFO:
            issues.append(_issue("NEW_INFO_DENSITY", "blocking", ep.episode_id,
                f"net-new info {len(set(ni))} < required {MIN_NEW_INFO}",
                "add genuine new mainline info; do not re-prove known facts"))
        # repeated explanation at episode level = duplicate new_info
        dup_ni = [x for x in ni if ni.count(x) > 1]
        if dup_ni:
            issues.append(_issue("REPEAT_EXPLANATION", "blocking", ep.episode_id,
                f"duplicate/new-info re-explained: {sorted(set(dup_ni))[:3]}",
                "remove repeated explanation; each info revealed once"))

        # ---- episode-level: events/min ----
        if total > 0:
            events = sum(1 for _, sh in ep.all_shots() if (sh.get("new_info") or sh.get("action", {}).get("result")))
            epm = events / (total / 60.0)
            if epm < MIN_EVENTS_PER_MIN:
                issues.append(_issue("EVENT_DENSITY", "warning", ep.episode_id,
                    f"events/min {epm:.1f} < {MIN_EVENTS_PER_MIN}",
                    "raise real-event density; cut non-advancing ambience"))

        # ---- scene-level: weather/time continuity + adjacency ----
        weathers = []
        for sc in ep.scenes:
            loc = f"{ep.episode_id}/{sc.get('scene_id')}"
            if not sc.get("weather"):
                issues.append(_issue("SCENE_WEATHER_MISSING", "blocking", loc,
                    "scene has no explicit weather", "set scene_state.weather (near source)"))
            else:
                weathers.append(sc["weather"])
            if not sc.get("time"):
                issues.append(_issue("SCENE_TIME_MISSING", "blocking", loc,
                    "scene has no explicit time", "set scene_state.time"))
        # adjacent-episode weather repeat (whole-episode monotony)
        if prev_weather and weathers and all(w == prev_weather for w in weathers):
            issues.append(_issue("WEATHER_ADJACENT_REPEAT", "warning", ep.episode_id,
                f"entire episode weather == previous episode ({prev_weather})",
                "vary weather vs adjacent episode unless source mandates"))

        # ---- shot-level ----
        for sc, sh in ep.all_shots():
            sid = sh["shot_id"]; loc = f"{ep.episode_id}/{sc.get('scene_id')}/{sid}"
            shot_penalty.setdefault(sid, 0)
            dur = float(sh.get("duration_sec", 0))
            # 4-15s plan
            if not (DURATION_MIN <= dur <= DURATION_MAX):
                issues.append(_issue("SHOT_DURATION_RANGE", "blocking", loc,
                    f"duration {dur}s outside {DURATION_MIN}-{DURATION_MAX}s",
                    "plan each shot within 4-15s to real performance beats"))
                penal(sid, 2)
            # action causality: contact/result
            act = sh.get("action") or {}
            is_action = bool(act.get("intent") or act.get("force") or act.get("contact"))
            if is_action:
                if not act.get("result"):
                    issues.append(_issue("ACTION_NO_RESULT", "blocking", loc,
                        "action shot has no result/consequence",
                        "give the action a visible result (force externalized on environment)"))
                    penal(sid, 2)
                if not act.get("contact") and act.get("force"):
                    issues.append(_issue("ACTION_NO_CONTACT", "warning", loc,
                        "force stated without visible contact/medium",
                        "show contact/medium that carries the force"))
                    penal(sid, 1)
            # visual-repeat (composition reuse)
            comp = (sh.get("composition") or "").strip()
            if comp:
                if comp in seen_compositions:
                    issues.append(_issue("VISUAL_REPEAT", "blocking", loc,
                        f"composition duplicates {seen_compositions[comp]}",
                        "vary framing/composition; no repeated shot images"))
                    penal(sid, 2)
                else:
                    seen_compositions[comp] = loc
            # dialogue: info-dump/length/subtext
            for j, dl in enumerate(sh.get("dialogue") or []):
                txt = str(dl.get("text", "")); dloc = f"{loc}#d{j}"
                if len(txt) > DIALOGUE_MAX_CHARS:
                    issues.append(_issue("DIALOGUE_TOO_LONG", "warning", dloc,
                        f"line {len(txt)} chars > {DIALOGUE_MAX_CHARS} (info-dump risk)",
                        "split/compress line; move exposition to subtext/visuals"))
                    penal(sid, 1)
                # info-dumping: dialogue that literally states a listed new_info verbatim
                for info in ni:
                    if info and info in txt and not dl.get("subtext"):
                        issues.append(_issue("INFO_DUMPING", "warning", dloc,
                            "dialogue states new info directly without subtext",
                            "deliver info via action/subtext, not direct statement"))
                        penal(sid, 1)
                        break
            # canon identity: speaker must exist in canon (if canon provided)
            if canon_chars:
                for dl in sh.get("dialogue") or []:
                    spk = dl.get("speaker")
                    if spk and spk not in canon_chars:
                        issues.append(_issue("CANON_UNKNOWN_CHARACTER", "blocking", loc,
                            f"speaker '{spk}' not in canon characters",
                            "use a canon character or register the new one first"))
                        penal(sid, 3)
            # identity attribute contradiction (e.g., locked age/gender in shot notes)
            for cid, cdata in (ep.canon.get("characters") or {}).items():
                lock = cdata.get("locked_traits") or {}
                note = (sh.get("first_frame_motion_state","")+" "+sh.get("composition","")+" "+sh.get("ambient_life",""))
                for trait, forbidden in (cdata.get("forbidden_depictions") or {}).items():
                    for bad in forbidden:
                        if bad and bad in note:
                            issues.append(_issue("IDENTITY_CONTRADICTION", "blocking", loc,
                                f"{cid} depicted with forbidden '{bad}' (locked {trait})",
                                f"respect locked trait {trait}={lock.get(trait)}"))
                            penal(sid, 3)
            # ambient_life presence unless deliberately static
            if not sh.get("ambient_life") and not sh.get("static_ok"):
                issues.append(_issue("AMBIENT_LIFE_MISSING", "warning", loc,
                    "no ambient_life and not marked static_ok (background may freeze)",
                    "add background life, or mark static_ok for deliberate-static shots"))
                penal(sid, 1)
            # first-frame motion state (anti 'pose then move')
            if not sh.get("first_frame_motion_state"):
                issues.append(_issue("FIRST_FRAME_MISSING", "warning", loc,
                    "no first_frame_motion_state (risk of completed-pose start)",
                    "first frame = mid-action off-balance moment, info incomplete"))
                penal(sid, 1)

        # ---- scoring: 5 minus penalties, thresholded by importance ----
        failed_shots = []
        for sc, sh in ep.all_shots():
            sid = sh["shot_id"]
            score = max(0, 5 - shot_penalty.get(sid, 0))
            shot_scores[sid] = score
            thr = KEY_PASS if sh.get("importance") == "key" else NORMAL_PASS
            if score < thr:
                failed_shots.append({"shot_id": sid, "score": score, "threshold": thr,
                                     "importance": sh.get("importance", "normal")})

        blocking = [i for i in issues if i["severity"] == "blocking"]
        # episode passes only if no blocking issue AND no shot below its threshold
        passed = (len(blocking) == 0) and (len(failed_shots) == 0)
        return {
            "schema": "backlotos.review_report.v1",
            "episode_id": ep.episode_id, "version": ep.version,
            "passed": passed,
            "total_duration_sec": round(ep.total_duration(), 1),
            "shot_scores": shot_scores,
            "score": round(sum(shot_scores.values()) / len(shot_scores), 2) if shot_scores else 0.0,
            "failed_shots": failed_shots,          # for failed-only revision
            "issues": issues,
            "blocking_count": len(blocking),
            "warning_count": len([i for i in issues if i["severity"] == "warning"]),
        }

    def failed_only_targets(self, report: dict) -> list:
        """Shot ids that must be re-generated (failed-only revision)."""
        ids = {f["shot_id"] for f in report.get("failed_shots", [])}
        for i in report.get("issues", []):
            if i["severity"] == "blocking":
                loc = i["location"]
                if loc.count("/") >= 2:
                    ids.add(loc.split("/")[-1].split("#")[0])
        return sorted(ids)
