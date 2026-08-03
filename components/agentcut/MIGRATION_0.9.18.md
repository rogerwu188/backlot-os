# AgentCut 0.9.18 migration: complete release project contracts

AgentCut 0.9.18 makes `releaseProject: true` a fail-closed declaration of a
complete distribution project. This prevents a render from reaching platform
preflight without subtitles or the Nalu Motion outro.

## Required fields

Explicit release projects must now include all of the following:

```json
{
  "releaseProject": true,
  "requireBurnedSubtitles": true,
  "expectedDialogueIds": ["D001", "D002"],
  "requireBrandedOutro": true,
  "outro": {
    "enabled": true,
    "brand": "nalu_motion",
    "includeInTotalDuration": true
  },
  "releaseGate": {
    "required": true
  }
}
```

The existing subtitle and outro validators continue to check actual caption
coverage, font/glyph support, asset readability, safe area, timing, and media
duration. The new contract gate checks that those validators cannot be disabled
on a release project.

## New failures

- `RELEASE_SUBTITLES_REQUIRED`
- `RELEASE_DIALOGUE_IDS_REQUIRED`
- `RELEASE_OUTRO_REQUIRED`
- `RELEASE_OUTRO_ENABLED_REQUIRED`
- `RELEASE_VISUAL_GATE_REQUIRED`

The same failures are emitted by compile, normal validation, strict media
validation, and render preflight. Non-release projects are unchanged.
