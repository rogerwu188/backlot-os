# Migration 1.0.1

- AgentCut 0.9.17 formal sidecars use `agentcut_shot_recipe_sidecar`, `agentcut_project`, `agentcut_render_manifest`, and `shot_recipe_provenance`.
- The provenance envelope requires non-empty `project_id` and `project_version`, plus exact `candidate_sha256`, `project_sha256`, `timeline_sha256`, and `manifest_sha256`.
- Existing snake_case fixture inputs remain compatible. Missing or mismatched provenance is never downgraded and cannot authorize intentional black/strobe.
- This patch is an installation candidate only; it does not modify or publish media and must be installed by Task2.
