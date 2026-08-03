# Audit — existing local Claude Writer (deliverable #1)

> Rule honored: "prompt exists" ≠ "capability executable". Below, each capability
> is classified by HOW it is actually realized today.

## A. Implemented by files / scripts / rules (portable as code)
- **Review/gate logic** exists as real Python in `tools/`: `density_gate_watch.py`,
  `dramatic_quality_gate.py`, `cut_motivation_gate.py`, `scene_authority_lock.py`,
  `script_density_gate_preflight.py`, `script_scene_diversity_gate.py`,
  `script_readiness_gate.py`, `action_xuanhuan_script_gate.py`. → deterministic, migratable.
- **Manifest/time accounting**: `workflow/claude_writer_agent/tools/validate_manifest_time_account.py`.
- **Structured episode artifacts**: `E{NN}_manifest*.json` (sha256/scene-shot counts/duration).

## B. Depends on the Claude / Cowork host (NOT portable without a model)
- **Actual script generation** (writing scenes/dialogue/action): there is **no**
  Anthropic API / Claude CLI / MCP entrypoint in the writer dir. Generation happens
  by Claude executing inside the Cowork session against prompt files
  (`宪章_ClaudeWriterAgent_v1.md`, `编剧agent_最新编剧要求_v1_20260723.md`). → host-dependent.
- **Scheduled runner** `qingshan-claude-writer-agent/SKILL.md` runs on the Claude host.

## C. Depends on current chat / session context
- Per-round orchestration ("read mailbox latest 3", 派单 in `PROGRESS.json`,
  batch cadence) is driven by the live session; not a standalone process.

## D. Depends on 《青山》-specific material (must NOT enter generic core)
- `原著对照档案_*.md`, character names (陈迹/皎兔/云羊), `full_series_information_node_map`,
  `观众已知清单.md`, project palettes/canon. → project-specific data; compat layer only.

## E. Abstractable to generic short-drama capability (this package)
- seven-check, density gate (≥4–6 events/min), FS-1 fight cadence, first-frame-motion,
  ambient-life tiering, weather continuity + adjacency, per-shot 4–15s, 5-point scoring,
  per-importance thresholds, failed-only revision, version/SHA/rollback.

## F. Executable entrypoints today
- Anthropic API: **none** in writer dir. Claude CLI: **none**. MCP: the host exposes tools,
  but no standalone story-generation MCP server. → **new** portable entrypoints are provided
  by this package (`claude_story_agent.cli`, NDJSON `serve`, adapter layer).

## Migration consequence
- **Review agent** → shipped as deterministic code (no model needed).
- **Story agent** → shipped as code + **adapter layer**; a model backend (Anthropic key OR
  external command) must be supplied on the target machine. Without it: CAPABILITY_FAIL.
