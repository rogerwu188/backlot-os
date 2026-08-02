# 0.3.2 migration

- Media-end rounding up to 50ms is safely clamped and audited as `BENIGN_BOUNDARY_ROUNDING_CLAMPED`; larger or structurally invalid ranges still produce `INVALID_ISSUE_TIME_RANGE`.
- OCR adjudication accepts `audit_scope.main_content_end` / `main_content_end_seconds` and preserves explicit `PASS_ADJUDICATED` evidence ahead of regression aggregates.
- Derived visual evidence can reuse an older audit only when it names the current media and its decoded-video MD5 matches `item.metadata.decoded_video_md5`. Accepted lineage is reported as `MATCH_DERIVED_DECODED_VIDEO_IDENTITY`.
- Ambience gain, periodic-loop, hiss and clipping thresholds are unchanged. No audio hard gate was relaxed.
- Report/request schemas remain v2/v1 compatible. Agent version is 0.3.2 and rules are `qingshan.review.rules.v14`.
