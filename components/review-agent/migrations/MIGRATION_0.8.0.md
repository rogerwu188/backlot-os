# qingshan-review-agent 0.8.0 migration

- Generic still images bind visual/OCR evidence by exact candidate SHA-256, independent of episode, batch directory, or evidence filename.
- Full-resolution OCR runs on demand via the bundled adapter and retains recognition confidence and region.
- Batch OCR is evaluated per current candidate. Low-confidence isolated OCR noise follows `qingshan.ocr.normalized-decision.v2` and no longer fails every sibling.
- Live semantic visual analysis uses `QINGSHAN_IMAGE_ANALYSIS_COMMAND` and the `qingshan.image_visual_runtime.request.v1` stdin contract. Missing runtime is an authoritative `CAPABILITY_FAIL`.
- Rule version changes from `qingshan.review.rules.v20` to `v21`; review IDs therefore change.
- No media, platform state, or old QA record is modified.
