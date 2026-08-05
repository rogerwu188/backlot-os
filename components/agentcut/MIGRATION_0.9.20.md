# AgentCut 0.9.20 Migration

AgentCut 0.9.20 closes two final-assembly gaps exposed by a repaired production
whose new media existed on disk while stale provenance survived in the edit.

## Replacement binding

When `metadata.replacementBindingPolicy.enabled` is true, AgentCut now scans all
enabled video and audio clips. It recalculates each source SHA, checks direct
source paths, and recursively checks every string inside clip metadata against
`forbiddenPathTokens`. A match fails validation with
`SUPERSEDED_SOURCE_STILL_BOUND` and records the exact metadata path in
`coverage.replacementBindings.residualClips`.

Builders should remove obsolete provenance instead of renaming its fields.
Native audio extracted from a superseded video must be rendered to a separately
admitted audio asset or explicitly replaced before release.

## Timeline overlap

Enabled clips may not overlap another enabled clip on the same video or audio
track. Put intentional picture-in-picture layers and audio mixes on separate
tracks. Accidental overlaps fail with `TIMELINE_SAME_TRACK_OVERLAP`; evidence is
reported at `coverage.timelineOverlaps`.
