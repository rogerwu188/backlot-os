# Capability Matrix

Legend: ✅ executable-as-code (tested) · ◐ code + requires model backend · ⚠ partial/heuristic · ❌ not portable (host-only)

## Story Agent (generation)
| Capability | Status | Where |
|---|---|---|
| Episode planning & mainline advance | ◐ | `story_agent.generate` + `prompts/story_generate.md` (needs model) |
| canon / identity / timeline constraints (input) | ✅ | passed in `canon`, enforced by review |
| audience-known-info management | ✅ | `canon.audience_known`; review flags re-proof |
| net-new-info check | ✅ | review `NEW_INFO_DENSITY` (>=6) |
| scene / shot / dialogue / action generation | ◐ | model via adapter; schema-validated |
| target + per-shot duration planning | ✅ | schema 4–15s + review `EPISODE_DURATION`/`SHOT_DURATION_RANGE` |
| visual change / action causality / scene diversity | ✅ | review `VISUAL_REPEAT`/`ACTION_NO_RESULT`/`WEATHER_ADJACENT_REPEAT` |
| structured JSON output | ✅ | `schemas/episode.schema.json` |
| failed-only revision | ✅◐ | `story_agent.revise` (enforces non-target preservation; regen needs model) |
| version / input SHA / output SHA / rollback | ✅ | `versioning.VersionLedger` |

## Script Review Agent (deterministic — no model)
| Check | Status | issue check id |
|---|---|---|
| declared canon character registration | ✅ | `CANON_UNKNOWN_CHARACTER` |
| declared forbidden identity depictions | ✅ | `IDENTITY_CONTRADICTION` |
| independent source fidelity | ❌ | requires source-fact evidence/model audit |
| inferred relationship continuity | ❌ | requires relationship evidence/model audit |
| time / weather / scene continuity | ✅ | `SCENE_WEATHER_MISSING`/`SCENE_TIME_MISSING`/`WEATHER_ADJACENT_REPEAT` |
| plot advance & new-info density | ✅ | `NEW_INFO_DENSITY`/`EVENT_DENSITY` |
| repeat explanation / bridge / composition | ✅ | `REPEAT_EXPLANATION`/`VISUAL_REPEAT` |
| action causality / contact / result | ✅ | `ACTION_NO_RESULT`/`ACTION_NO_CONTACT` |
| dialogue naturalness / subtext / info-dump | ✅⚠ | `DIALOGUE_TOO_LONG`/`INFO_DUMPING` (heuristic) |
| per-episode target duration | ✅ | `EPISODE_DURATION` |
| per-shot 4–15s plan | ✅ | `SHOT_DURATION_RANGE` |
| 5-point scoring | ✅ | `shot_scores` (5 − penalties) |
| per-shot-importance pass threshold | ✅ | key≥4 / normal≥3 |
| blocking / warning / fix / stable issue_id | ✅ | `issues[].issue_id` (sha1 of check+location) |
| failed-only targets | ✅ | `failed_only_targets()` |

## Runtime
| Feature | Status |
|---|---|
| generate/review/revise/validate/health/status/progress | ✅ |
| generateMany / reviewMany | ✅ |
| >=4 workers (floor enforced) | ✅ |
| NDJSON persistent protocol | ✅ |
| single-shot CLI | ✅ |
| model adapter: anthropic / command / mock | ✅ (anthropic needs key+pkg) |
| CAPABILITY_FAIL when no model (no fake PASS) | ✅ |
| no key written/returned/guessed | ✅ |
| model output structural validation | ✅ |
| failed-only scene/shot topology protection | ✅ |
| append-only rollback snapshots | ✅ |
