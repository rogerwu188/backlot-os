# Audit -- backlotos-producer-supervisor-agent

> Rule honored: "code exists" != "capability executable against a live
> service". Each capability below is classified by how it is actually
> realized, mirroring `components/story-agent/AUDIT.md`'s method.

## A. File/code-implemented AND tested (portable, no external service needed)
- Intake structural validation (`intake_validate.py`) -- stdlib default, real
  test coverage (valid + invalid payloads).
- Episode/stage/agent-owner/concurrency/retry planning (`plan.py`) -- pure
  structural scaffolding, no model call.
- Idempotent job ledger + per-key locking + dedup (`dispatch.py`) -- real,
  concurrency-tested (40 concurrent distinct-key dispatches -> exactly 40
  ledger lines; 10 concurrent identical-key dispatches -> exactly 1 downstream
  invocation and 1 ledger line).
- Batch dispatch propagates internal failures to top-level status; partial or
  zero-pass batches cannot be reported as successful tool runs.
- Resume-from-interruption and retry-failed-only (`dispatch.py`) -- real,
  tested against a simulated partial ledger.
- Cost aggregation, `NOT_REPORTED` honesty, duplicate-charge detection
  (`cost.py`) -- real, mirrors `backlotos_launcher.pipeline.credit_summary()`
  disk format exactly.
- Cross-stage evidence supervision, including `NOT_RUN` honesty for
  unexecuted checks (`supervise.py`) -- real.
- Missing/stale provenance now blocks, and repeated final-duration evidence is
  reconciled rather than incorrectly summed across stages.
- Review-report -> PASS/ADVISE/BLOCK decision, never downgrading BLOCK
  (`review_decision.py`) -- real, tested with adversarial bypass-flag payloads.
- Human-authorization boundary (`runtime.py::_is_irreversible_request`) --
  real, tested across 7 irreversible verbs x 5 flag-bypass-attempt
  combinations = 35 assertions, all blocked.
- NDJSON `serve` loop and minimal stdlib HTTP server (`runtime.py`,
  `http_server.py`) -- real, round-trip tested in-process on an ephemeral
  port.
- The `backlotos-producer-command` / `backlotos-pipeline-command` console
  scripts -- real, satisfy `agent_host._external()`'s exact protocol
  (one JSON in, one JSON out, no shell, non-zero on structured failure), smoke-tested via the actual
  installed console scripts on the command line. Version 0.1.1 was installed
  from its wheel in a fresh environment and both health paths were exercised.

## B. Depends on a live downstream agent/service (ADAPTER_REQUIRED/CAPABILITY_FAIL until deployed)
- Actually executing a dispatched job against `story`/`pipeline`/`post`/
  `review` (`AgentInvoker.invoke()`) requires a configured `command` or `http`
  backend per agent. No backend is configured by default in this sandbox;
  `dispatch` honestly reports `BLOCKED`/`CAPABILITY_FAIL` rather than
  fabricating `COMPLETED` (tested explicitly).
- `backlotos-pipeline-command`'s `storyboard-generation`/`media-generation`
  paths -- there is no image/video/audio generation provider in this sandbox,
  and none is faked; both report `ADAPTER_REQUIRED`.
- End-to-end operation inside the live `deploy/five-agent` docker-compose
  stack -- not run in this sandbox (no docker). `MIGRATION.md` documents the
  wiring but this is NOT claimed as verified.

## C. Depends on a real human action (never automatable by design)
- Any publish/release/delete/overwrite-final/platform-upload/platform-delete/
  human_release_authorization action -- `runtime.py` blocks these
  unconditionally before any verb executes; there is no in-package code path
  that performs them, and no payload flag changes this.

## D. Pipeline-tools gate modules -- reused vs not, and why

Reused as-is (imported live, `evaluate(payload)`/`evaluate_plan_rows(...)`
called directly, no modification to the original files):
- `dramatic_quality_gate.py`, `common_sense_causality_gate.py`,
  `anti_padding_gate.py`, `action_visualization_readability_gate.py`,
  `cut_motivation_gate.py`, `defect_tolerance_gate.py`,
  `edit_plan_integrity_gate.py` -- each takes a plain payload/rows argument
  and returns a dict; none hardcodes an episode number or source-drama character
  name in its `evaluate` logic (comments/docstrings in
  `cut_motivation_gate.py` reference past episode incidents as historical
  rationale, but the function itself operates only on the passed-in
  `project`/`metrics` dict).

Found NOT generic enough to reuse as a payload evaluator (left untouched,
NOT imported, NOT modified):
- `continuity_auditor.py` -- a full CLI tool that shells out to `ffmpeg` and
  operates on real video files on disk; no `evaluate(payload)` entrypoint
  exists to wrap.
- `density_gate_watch.py` -- a `main()`-driven watch-loop CLI, not a payload
  evaluator.
- `evidence_gate_watch.py` -- a filesystem token-scanner CLI (`scan(root,
  tokens, excluded)`), not a payload evaluator; also inherently reads
  arbitrary project directories, which is out of scope for a stateless gate
  wrapper.

Episode-specific one-off scripts (`build_e*.py`, `audit_e*.py`,
`finalize_e*.py`, and any other filename encoding an episode number or
source-drama character name) were not opened for reuse consideration beyond
confirming their filenames match the excluded pattern -- they are out of
scope per the task brief and were not touched.

## E. Local acceptance

The imported 0.1.0 delivery passed its original 71 tests. After fixing
top-level batch status, evidence fail-closed behavior, duration reconciliation,
HTTP 404 handling, intake ambiguity and deployment wiring, version 0.1.1
passes 83 package tests. Story Agent passes 27 regression tests and Launcher
passes 28 regression tests. The 0.1.1 wheel and sdist build normally; the wheel
was installed and health-checked in a fresh Python environment. Docker was not
available locally, so five-service Compose acceptance remains pending.
