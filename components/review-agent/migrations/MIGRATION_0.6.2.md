# qingshan-review-agent 0.6.2 migration

- Explicit `qingshan.final_video_ocr_audit.v2` normalized decisions are authoritative only when status passes, lexicon policy is configured, `critical_text_failures=0`, and normalized Latin/Chinese/numeric failure aggregates are empty.
- Raw OCR recognitions are always preserved in capability evidence. Rejected raw candidates now include a machine-readable rejection reason.
- Without an authoritative clean decision, a raw recognition becomes readable text only when it is explicitly forbidden, contains meaningful characters and has confidence >=0.85, or persists across at least two adjacent samples.
- Isolated symbols and unstable low-confidence number fragments no longer create blocking native-text issues.
- Persistent real text and explicitly forbidden text remain blocking. OCR coverage, exact outro boundary, watermark and all non-OCR gates are unchanged.
- A raw v2 audit may be reassessed from FAIL to `PASS_POLICY_NORMALIZED_RAW_FAIL` when every recognition is rejected by the same policy gates. Its original FAIL, `critical_text_failures`, character counts, recognitions and rejection reasons remain in the capability evidence.
- Latin/numeric candidates require both confidence >=0.85 and persistence; configured-lexicon Chinese explicitly marked `unlisted_chinese=false` and explicit subtitle-region/classification hits are allowed. Unlisted Chinese still requires confidence or persistence.
- Agent version is 0.6.2; rule version is `qingshan.review.rules.v19`.
