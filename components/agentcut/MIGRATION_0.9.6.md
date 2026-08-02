# AgentCut 0.9.5 → 0.9.6

0.9.6 is an additive port on the accepted 0.9.5 production baseline. It does not replace the CFR half-open boundary strategy, invisible EOF sentinel, release black-frame policy, cadence regression, measured two-pass loudness mastering, strict continuity metadata, burned subtitles, narrative gate, branded outro, or renderMany behavior.

Before activation, compare the 0.9.5 and 0.9.6 NDJSON `health.result.capabilities` objects after removing only the new `longTake` and `giggleFirstLast` keys. They must be byte-equivalent after canonical JSON sorting.

New production flow:

1. Call `prepareFirstLastGeneration` before any paid request.
2. Execute the returned argv only when `allowed=true`, the endpoint is `/api/v1/generation/image-to-video`, and exactly the `start_frame`/`end_frame` roles are present.
3. Download the generated candidate without replacing admitted production media.
4. Call `finalizeFirstLastGeneration`; reject when `accepted=false`.
5. Run cadence, OCR, and ASR separately.

Rollback is the existing isolated-environment operation: retain the 0.9.5 wheel and reinstall it into the environment if Task2 acceptance fails. Project and media schemas are backward compatible.
