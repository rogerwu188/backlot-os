# AgentCut 0.9.5 migration

No project JSON changes are required.

- Upgrade from 0.9.4 is required for release renders. Version 0.9.4 can suppress hard-cut black frames by visibly repeating a source tail and is not cadence-safe.
- Video timeline offsets and handoff windows are now exact frame/fps rational expressions. Shortened decimal PTS are no longer emitted.
- `overlay` uses `eof_action=pass:repeatlast=0`; visible source-tail repetition is forbidden.
- A single EOF sentinel is materialized one frame outside each clip's half-open visual range. It is never visible, does not extend the timeline, and is not padding.
- Audio timing remains exact and unquantized.
- Release QA must pass both `blackframe=amount=95:threshold=32` with zero detections and the production cadence audit with no unmotivated freeze or periodic duplicate chain.

Existing projects render unchanged. Re-render any candidate produced by 0.9.4 before release review.
