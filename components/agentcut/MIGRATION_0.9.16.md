# AgentCut 0.9.16 Migration

0.9.16 adds Giggle text-to-audio generation for dialogue and voiceover clips.

## New capability

- NDJSON: `listSpeechVoices`, `generateSpeech`, `querySpeech`
- CLI: `speech-voices`, `speech-generate`, `speech-query`
- Credential: `GIGGLE_API_KEY` from the process environment only
- Output: one atomically downloaded MP3 that can be used directly as an `Audio.Dialogue` clip `source`

## Security and release gates

AgentCut never accepts the Giggle API key in project JSON or CLI arguments. Public AgentCut responses remove provider signed URLs and return only local file receipts.

Giggle currently does not return verifiable commercial-use metadata for speech results. Generated dialogue is therefore `releaseEligible=false` until media probing, dialogue timing, human listening, and commercial-rights gates pass.

## Rollback

Downgrade to 0.9.15 if a caller depends on the older health capability map. Existing render, BGM, character-card, long-take, and first/last generation interfaces are unchanged.
