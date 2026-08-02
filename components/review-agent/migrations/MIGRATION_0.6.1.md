# qingshan-review-agent 0.6.1 migration

- `audio.rms_jump` is now measured from short decoded-final windows immediately before and after real AgentCut materialized boundaries.
- Fixed 0.5-second/whole-section RMS deltas are preserved as `audio.rms_window_delta_raw` informational evidence and never deduct score by themselves.
- A boundary delta above 12 dB remains actionable when the local decoded-final window detects digital zero, dropout, or a click. Continuous dialogue/music dynamics are retained as motivated info.
- Thresholds are unchanged. Audio digital-zero, long-silence, clipping, ambience, freeze, black-frame and copyright hard gates are unchanged.
- Agent version is 0.6.1 and rule version is `qingshan.review.rules.v18`; deterministic review IDs change.
