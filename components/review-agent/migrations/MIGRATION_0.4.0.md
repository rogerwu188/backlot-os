# 0.4.0 migration

- New Seedance/video-generation reviews must provide `task.duration_plan.duration_seconds`. Plans are valid from 4 through 15 seconds; there is no global 6-second maximum.
- Actual media duration must match the per-shot plan within ±0.20 seconds by default. `duration_tolerance_seconds` can be set from 0 to 1 and enters the review fingerprint.
- Reports add `story_duration` and a required `story_duration` capability with planned duration, actual duration, delta, policy, result and rollback state. Missing, out-of-range and mismatched plans are blocking.
- `reviewMany` protocol/CLI output is now `qingshan.review_many.result.v2`: all reports remain in ordered `items`; only failed requests appear in `retry_items`. Default concurrency remains 4 workers.
- `evidence_inputs.cadence_audit` can supply existing frame-cadence JSON. Periodic duplicate, freeze and black-frame findings remain blocking. OCR, audio and ASR gates are unchanged.
- Version: Agent 0.4.0; rules `qingshan.review.rules.v15`. No publish/delete/platform operation was added.
