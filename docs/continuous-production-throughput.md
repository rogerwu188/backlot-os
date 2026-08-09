# Continuous production and real throughput

BacklotOS treats a heartbeat as a watchdog, not as the production driver.  A
task completion must expose the next READY work immediately and the continuous
dispatcher must claim that work while a local slot is available.

## Definition of complete

Prompt compilation, reference planning, and static QA are useful intermediate
work.  They do not count as an admitted clip or as completed video seconds.
Run `shot_package_completion_gate.py` against the episode inventory.  A package
is complete only when it has all of the following exact bindings:

- canonical and manifest SHA agreement;
- a precompiled prompt and standard `seedance-2.0` generation contract;
- an exact first frame and contiguous ordered references;
- applicable character, wardrobe, scene, and prop asset SHAs;
- accepted exact audio and lip-sync evidence when dialogue is visible, or an
  explicit offscreen/narration transport waiver;
- completed output media with positive measured duration;
- QA admission bound to the exact output SHA.

The gate reports four audience-facing throughput metrics:

- `completed_packages`;
- `admitted_video_seconds`;
- `assembly_ready`;
- `precompile_only`.

Operational dashboards and work queues should lead with these values.  A high
precompile count with zero admitted seconds is not episode completion.

## Continuous dispatch

`continuous_task_lane_dispatcher.py` supports a one-cycle audit or a persistent
watch loop.  READY work is ranked with shot deliverables ahead of precompile
work, then by explicit task priority.  RUNNING and QA consume local slots;
task-local REMOTE_WAIT does not unless explicitly configured.

Each READY task must include a typed `dispatch` descriptor:

```json
{
  "task_id": "E40-U04-START-FRAME",
  "lane_id": "SHOT_PACKAGE",
  "state": "READY",
  "zero_cost": true,
  "deliverable_type": "SHOT_PACKAGE",
  "priority": 100,
  "dispatch": {
    "kind": "command",
    "argv": ["python3", "tools/build_e40_u04_start_frame.py"],
    "cwd": ".",
    "idempotency_key": "E40:U04:start-frame:v1"
  }
}
```

Commands are argv arrays and never shell strings.  Event dispatch is also
supported with `kind=event`, an in-root `event_path`, and a JSON `payload`.
Before any process or event is created, the dispatcher atomically persists an
idempotent intent.  A successful dispatch then changes the task to RUNNING.
Restarting the controller reuses the durable dispatch instead of duplicating
work.

Applied dispatch cycles hold a per-state-file single-writer lease across the
journal claim and scheduler update. Scheduler persistence uses the exact input
file SHA as a compare-and-swap precondition. If an unlocked writer changes the
file meanwhile, the dispatcher reloads the latest state and merges only its
own changed `task_id` records; a same-task conflict fails closed. Every state
and journal write uses a same-directory temporary file, file `fsync`, atomic
rename, and directory `fsync`, so neither concurrent agents nor a process crash
can silently restore a stale whole-file snapshot.

Example production loop:

```bash
python3 continuous_task_lane_dispatcher.py \
  --root /srv/qingshan \
  --state /srv/qingshan/workflow/production_line/E40_TASK_LANES_V1.json \
  --journal /srv/qingshan/workflow/runtime/E40_CONTINUOUS_DISPATCH.json \
  --capacity 3 --watch --apply
```

The external scheduler or service manager owns this process.  A ten-minute
cron remains useful only to detect and recover a missing dispatcher.

## Legal blockers and false idle

`task_lane_global_wait_gate.py` rejects an unfinished scheduler that has no
READY, live producing/QA work, or task-local REMOTE_WAIT unless
`scheduler_decision` carries a typed `legal_blocker` with:

- `code`;
- `evidence_ref`;
- `next_recheck_at`.

This prevents a queue containing only WAITING_DEPENDENCY tasks from being
reported as healthy while production has silently stopped.

A persisted `RUNNING` label is not proof of a live worker. Every RUNNING task
must bind `lease_owner`, `lease_expires_at`, `last_progress_at`, and
`next_due_at`; an expired lease or missed progress deadline is excluded from
active-successor accounting. Tasks marked `liveness_role=OBSERVATION`,
`observation_only=true`, or represented by watchdog/monitor receipt
deliverables remain useful for diagnostics but cannot by themselves satisfy
episode continuity. The continuous dispatcher writes an initial bounded lease;
the owning worker must renew progress and due timestamps while it runs.

## Retry strategy changes

Run `retry_strategy_change_gate.py` before every paid retry.  The predecessor
must be VERIFIED_ZERO or fully refunded, and both prompt and input SHAs must
change.  After two failures in the same failure family and representation, a
third paid attempt requires a validated strategy change with evidence.  The
supported changes are shot split, transport change, deterministic composite,
and asset isolation.  Small prompt edits are not a strategy change.
