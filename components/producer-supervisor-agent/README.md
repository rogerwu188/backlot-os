# backlotos-producer-supervisor-agent

Producer / Supervisor agent for BacklotOS: episode planning, idempotent job
dispatch, cross-stage evidence supervision, credit-ledger cost aggregation,
resume/retry-failed recovery, and PASS/ADVISE/BLOCK review decisions. Generic,
stdlib-only core -- no source-drama-specific content anywhere in `src/`,
`schemas/`, or `tests/` (verified by `tests/test_security_and_content_scan.py`).

This package IS the real implementation behind the two external-command
adapters `backlotos_launcher.agent_host` already expects:

- `BACKLOT_PRODUCER_COMMAND=backlotos-producer-command`
- `BACKLOT_PIPELINE_COMMAND=backlotos-pipeline-command`

Both scripts read one JSON request on stdin (`{"method"|"verb": ..., "params": {...}}`)
and write exactly one JSON object to stdout. They use a non-zero exit for a
content/capability failure; `agent_host.py` preserves that structured JSON and
exit code so a generic supervisor cannot mistake an internal failure for tool
success (argv, no shell, no extra stdout).

## Install

```bash
pip install -e components/producer-supervisor-agent
```

## Console scripts

- `backlotos-producer-command` -- BACKLOT_PRODUCER_COMMAND adapter.
- `backlotos-pipeline-command` -- BACKLOT_PIPELINE_COMMAND adapter; wraps the
  GENERIC pipeline-tools gates (see CAPABILITY_MATRIX.md) as verb-dispatched
  semantic checks plus `providerHealth`, `generateImage`, `generateVideo`, and
  `taskStatus` for Giggle. Its `parallelQa` method fans independent QA checks
  out concurrently and waits at one aggregate barrier; one failed check never
  cancels its siblings. It reports honest `ADAPTER_REQUIRED` without
  `GIGGLE_API_KEY`. Defaults: image `gpt2img`, video `seedance-2.0-pro`.
- `backlotos-producer-agent` -- standalone entrypoint (single-shot CLI /
  `serve` NDJSON loop / `serve-http` minimal HTTP server), for running this
  package directly outside the launcher's external-command proxy. Mirrors
  `claude-story-agent`'s CLI conventions.

## Verbs

`health`, `validate`, `plan`, `dispatch`, `dispatchMany`, `supervise`,
`status`/`progress`, `resume`, `retry-failed`/`retryFailed`,
`cost-summary`/`costSummary`, `review-decision`/`reviewDecision`.

Any verb, or any `params.action`/`params.stage`, that implies a publish /
delete / overwrite-final / irreversible platform action returns
`{"ok": false, "status": "BLOCKED", "reason": "HUMAN_AUTHORIZATION_REQUIRED"}`
unconditionally -- no payload flag (`force`, `confirm`, `override`, ...) can
bypass this. See `tests/test_human_authorization_and_capability.py`.

## Parallel QA rule

As soon as a candidate asset is available, launch all independent checks for
that asset together: visual quality, dialogue completeness and duplication,
OCR, character/voice identity, action-space and outcome continuity, cadence,
and exact credit reconciliation. Different completed assets use the same
fan-out concurrently. Only final acceptance waits for every required result.

Generation dependencies such as `previous tail frame = next first frame` stay
serial. That dependency never serializes QA checks that do not depend on one
another. Invoke the executable rule with:

```json
{"method":"parallelQa","params":{"workers":8,"receipt_path":"qa/receipt.json","tasks":[{"qa_id":"U07.visual","gate":"action-visualization-readability","payload":{}},{"qa_id":"U07.causality","gate":"common-sense-causality","payload":{}}]}}
```

## On-disk contract (compatible with `backlotos_launcher.pipeline`)

- `<project>/plan.json` -- Producer's episode/stage/agent-owner/concurrency plan.
- `<project>/jobs.ndjson` -- append-only idempotent job ledger (fsync per write).
- `<project>/credits.ndjson` -- same shape as `contracts/credit-event.schema.json`,
  read/written the same way `backlotos_launcher.pipeline.record_credit()` does.
- `<project>/episodes/*.json` -- read (not owned) when present, for `status`.

This package re-implements (does not import) the launcher's atomic-write and
NDJSON-append primitives in `ledger.py`, so it has no hard runtime dependency
on `backlotos-launcher`, while staying byte-compatible with its file shapes.

## Idempotent dispatch

`dispatch` computes `idempotency_key = sha256(episode_id|stage|sha256(payload))`
and serializes concurrent calls for the same key with an in-process lock, so
the downstream agent is invoked at most once per key even under concurrent
`dispatchMany` calls. A second call with the same key returns the existing
ledger record with `"deduped": true` and does not re-invoke the agent.

## Tests

```bash
python3 -m pytest components/producer-supervisor-agent/tests -q
```

See `TEST_REPORT.json` for the latest programmatically generated acceptance
report from the real pytest/junitxml run.

## Build

`python -m build components/producer-supervisor-agent` produces the wheel and
sdist. Version 0.2.1 includes the parallel QA fan-out and aggregate barrier.
