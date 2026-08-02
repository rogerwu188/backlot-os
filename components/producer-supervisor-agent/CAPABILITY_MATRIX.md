# Capability matrix -- backlotos-producer-supervisor-agent

Legend: **SUPPORTED** = real code, exercised by a real passing test in this
delivery. **ADAPTER_REQUIRED** = code path exists and fails closed honestly
until a live downstream service/provider is configured. **HUMAN_ONLY** =
intentionally never automatable.

| Capability | Verb | Status | Notes |
|---|---|---|---|
| Intake validation | `validate` | SUPPORTED | Hand-rolled default (stdlib-only); uses `jsonschema` opportunistically if importable, with automatic fallback on any incompatibility. |
| Episode/stage planning | `plan` | SUPPORTED | Structural scaffolding only (chapter chunking, stage sequence, agent-owner map, concurrency/retry policy). Never writes prose. |
| Idempotent job dispatch | `dispatch`, `dispatchMany` | SUPPORTED (ledger) / ADAPTER_REQUIRED (actual downstream call) | Idempotency, dedup, and the append-only `jobs.ndjson` ledger are real and tested. Actually reaching `story`/`pipeline`/`post`/`review` requires a configured `AgentInvoker` backend (`BACKLOT_AGENT_<NAME>_COMMAND`/`_URL`); without one, jobs are honestly recorded `BLOCKED`/`CAPABILITY_FAIL`, never fabricated `COMPLETED`. |
| Cross-stage evidence supervision | `supervise` | SUPPORTED | Identity/version consistency, sha256 format + file-match verification, stale-evidence-by-version and by-timestamp, duration compliance, padding heuristic (advisory). Every check that cannot run reports `NOT_RUN`, never `PASS`. |
| Aggregate status/progress | `status`, `progress` | SUPPORTED | Reads real `episodes/*.json` and/or `plan.json` + `jobs.ndjson`; no cached/fabricated numbers. |
| Resume after interruption | `resume` | SUPPORTED | Read-only; computes next actionable stage per episode from the ledger. Does not re-dispatch. |
| Retry only failed jobs | `retry-failed`/`retryFailed` | SUPPORTED | Scans reduced (latest-per-key) ledger state; touches only `FAILED`; `COMPLETED`/`BLOCKED` are untouched (tested). |
| Cost aggregation | `cost-summary`/`costSummary` | SUPPORTED | Mirrors `backlotos_launcher.pipeline.credit_summary()` disk format exactly. `NOT_REPORTED` (never `0`) when no events exist for a stage/episode. Detects `POSSIBLE_DUPLICATE_CHARGE` across distinct `cost_key`s sharing a `(provider, provider_task_id)`. |
| Review gate decision | `review-decision`/`reviewDecision` | SUPPORTED | Never rewrites prose; only proposes structured revision requests + a PASS/ADVISE/BLOCK decision. Cannot be downgraded from BLOCK by any payload flag (tested). |
| Human-authorization boundary | any verb / `action`=publish,release,delete,overwrite_final,platform_upload,platform_delete,human_release_authorization | ENFORCED, no bypass | Checked before any verb executes. No `force`/`confirm`/`override` flag has any effect (tested across 7 verbs x 5 flag combinations). |
| `backlotos-producer-command` (BACKLOT_PRODUCER_COMMAND) | -- | SUPPORTED as external-command adapter | One JSON in / one JSON out, no shell, non-zero on structured failure. `agent_host._external()` preserves the JSON and exit code. |
| `backlotos-pipeline-command` (BACKLOT_PIPELINE_COMMAND) | `health`, `gate`, `edit-plan-integrity`, `providerHealth`, `generateImage`, `generateVideo`, `taskStatus` | SUPPORTED; live generation is ADAPTER_REQUIRED until configured | Generic gates plus a Giggle provider. Credential is environment-only. Defaults are `gpt2img` and `seedance-2.0-pro`. |
| NDJSON `serve` loop | `backlotos-producer-agent serve` | SUPPORTED | One JSON request per line in, one JSON reply per line out, flushed per line. |
| Minimal HTTP server | `backlotos-producer-agent serve-http` (`GET /health`, `POST /v1/task`) | SUPPORTED | Same wire shape as `agent_host.RoleServer`/`RoleHandler`. Stdlib `ThreadingHTTPServer` only, no framework dependency. |
| Live 5-agent docker-compose end-to-end run | -- | NOT RUN | No docker available in this sandbox; not claimed as verified. See `deploy/five-agent/roles.json` `adapter_available` field. |

## Pipeline-tools gates wrapped by `backlotos-pipeline-command`

| Gate | Module | Status |
|---|---|---|
| dramatic-quality | `dramatic_quality_gate.py` | SUPPORTED (loaded + `evaluate(payload)` callable) |
| common-sense-causality | `common_sense_causality_gate.py` | SUPPORTED |
| anti-padding | `anti_padding_gate.py` | SUPPORTED |
| action-visualization-readability | `action_visualization_readability_gate.py` | SUPPORTED |
| cut-motivation | `cut_motivation_gate.py` | SUPPORTED |
| defect-tolerance | `defect_tolerance_gate.py` | SUPPORTED |
| edit-plan-integrity | `edit_plan_integrity_gate.py` (`evaluate_plan_rows`) | SUPPORTED (requires sibling `frame_cadence_audit`/`run_regression_ci` modules, resolved automatically by adding `pipeline-tools/` to `sys.path` during load) |
| continuity-auditor | `continuity_auditor.py` | ADAPTER_REQUIRED -- operates on real video files via an `ffmpeg` CLI subprocess pipeline, not a `payload: dict -> dict` evaluator; not wrapped here. |
| density-gate-watch | `density_gate_watch.py` | ADAPTER_REQUIRED -- a watch-loop CLI utility, not a payload evaluator. |
| evidence-gate-watch | `evidence_gate_watch.py` | ADAPTER_REQUIRED -- a filesystem token scanner CLI, not a payload evaluator. |
| storyboard-generation / media-generation | Giggle | SUPPORTED when `GIGGLE_API_KEY` is configured; otherwise ADAPTER_REQUIRED. Paid generation is invoked only through explicit generate methods, never by the readiness gate. |

All statuses above are returned literally by `backlotos-pipeline-command health`
via `pipeline_gates.health()` -- run it yourself to reconfirm at any time.
