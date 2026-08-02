# AgentCut 0.9.11 migration

0.9.11 is an additive upgrade from 0.9.10. Existing project JSON, render behavior, release gates, character cards, conditional rough assembly, CLI, SDK, and NDJSON methods remain unchanged.

## Enable BGM generation

Inject `GIGGLE_API_KEY` into the AgentCut process environment. Do not place it in project JSON, source files, command arguments, logs, or release artifacts. Confirm `health.capabilities.bgmGeneration` before dispatching work.

Use `generateBgm` with an instrumental prompt and caller-owned output directory. The worker submits once, polls every 15–60 seconds, downloads candidates atomically, and returns local paths and hashes without exposing provider signed URLs.

Generated files are deliberately returned with `releaseEligible=false`. Before release, the parent workflow must probe the media, confirm no vocals, measure loop seams and loudness, listen for artifacts, and attach commercial-use/license metadata. The existing AgentCut audio track accepts the returned local MP3 path as a normal audio clip source.

## Rollback

Reinstall the retained 0.9.10 wheel and restart the worker. No project migration or data rewrite is required. Requests using `generateBgm` or `queryBgm` must be removed or routed to the previous external music worker after rollback.
