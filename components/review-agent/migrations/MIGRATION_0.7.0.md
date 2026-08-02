# qingshan-review-agent 0.7.0 migration

- `review-many` now has authoritative top-level `status` and `content_status`: `PASS`, `CONTENT_FAIL`, or `CAPABILITY_FAIL`.
- Any failed item makes the CLI exit nonzero. Supervisors must parse top-level status when available and must never infer content PASS solely from process startup/success.
- Individual reports distinguish `FAIL` (content) from `CAPABILITY_FAIL` (required adapter/evidence unavailable). Missing capabilities never become content findings or PASS.
- Added `image_analysis` and `sequence` scope. Storyboard-sheet reviews reuse SHA-bound `qingshan.storyboard_sheet_ai_visual_adjudication.v1` production evidence.
- The adapter unifies six-column/six-row layout, composition diversity, identity/location continuity, panel OCR, modern-object, SETUP/IMPACT/TABLEAU, close/wide scale and environmental-power checks.
- A missing required semantic check is `CAPABILITY_FAIL`; a failed supplied check creates a stable blocking issue with evidence/region/confidence.
- Agent version is 0.7.0; rule version is `qingshan.review.rules.v20`.
