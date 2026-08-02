# qingshan-review-agent 0.6.0 migration

- Final pacing now reconciles raw pixel scene detection with a provenance-matched AgentCut materialized timeline.
- An episode anti-padding contract can adjudicate `runtime_min` and `under1_min` only when it is active, episode-matched, padding-forbidden, shorter-runtime-enabled, coverage-complete, and overlap-free.
- Raw detector failures and measurements remain in `video.runtime_min_reconciled` and `video.pacing_reconciled` evidence; these informational findings do not deduct score.
- Existing hard gates for black/freeze/periodic duplicate/OCR/audio/ASR/copyright and incomplete coverage are unchanged.
- Rule version is `qingshan.review.rules.v17`; review IDs therefore change deterministically.
