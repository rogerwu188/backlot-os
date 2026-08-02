# qingshan-review-agent 0.9.1 migration

- Full-cut OCR now consumes `evidence_inputs.ocr_raw` and `evidence_inputs.ocr_adjudication` in addition to legacy `ocr`.
- Exact-frame machine adjudication requires exact candidate path/SHA, exact raw report path/SHA, preserved raw result, visual evidence path/SHA, confidence >= 0.90, zero critical findings, and no platform mutation authorization.
- Raw OCR `FAIL` remains visible as `raw_status`; a valid false-positive adjudication becomes `PASS_MACHINE_ADJUDICATED_EXACT_FRAMES`.
- An OCR audit that stops before the current media/main-content end triggers an on-demand RapidOCR gap scan. Any gap hit is evaluated independently and is not covered by the earlier adjudication.
- Missing/mismatched evidence never reports OCR as executed or passed.
- Rule version changes to `qingshan.review.rules.v23`; review IDs change. No platform content is modified.
