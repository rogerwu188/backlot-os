# 0.3.1 migration

- OCR review boundaries now use a provenance-validated AgentCut outro boundary. Explicit `outro.actualStart` wins; an enabled outro falls back to the materialized main video timeline end.
- OCR evidence may declare coverage with `review_end_seconds`, `sample_end_seconds`, `sampled_through_seconds`, or `exclusion_start_seconds`. Coverage ending before main content is an ERROR and blocking issue, never PASS.
- Without a trusted outro manifest, OCR must cover the complete media duration. Known outro branding is classified by allowlist instead of blind tail exclusion.
- Main-content readable text produces stable `video.readable_native_text` or `video.readable_native_text_duplicate` issues. Existing report/request schemas remain compatible; `ocr_brand_allowlist` is additive.
- Read-only behavior is unchanged. No publish, delete, or platform action is introduced.
