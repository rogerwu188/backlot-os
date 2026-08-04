# Changelog

## 0.9.20

- Scan every enabled video and audio clip for forbidden superseded source SHA
  values, source-path tokens, and recursively nested metadata provenance.
- Reject same-track video or audio timeline overlaps before compile or render;
  intentional composites and mixes must use separate tracks.
- Report live-clip, metadata-hit, and overlap evidence in validation coverage so
  repaired media cannot pass QA while the final project remains bound to stale
  sources.

## 0.9.18

- Make `releaseProject:true` a complete, fail-closed distribution contract.
- Require burned subtitles, non-empty expected dialogue IDs, the enabled Nalu
  Motion branded outro, and `releaseGate.required=true` before compile or render.
- Expose `coverage.releaseProjectContract` in normal and strict validation so
  clients can diagnose missing declarations before media work begins.
- Preserve compatibility for non-release projects and independently reviewed
  rough candidates; only explicitly designated releases activate the contract.

## 0.9.17

- Add a versioned registry of 27 curated live-action/generated-short-drama shot recipes with Apache-2.0 source/NOTICE provenance and no Remotion or bundled-audio dependency.
- Preserve resolved recipe metadata and project/clip overrides through validation coverage, materialized timeline, compile director render plan, render manifest, and a SHA-bearing sidecar.
- Reject unknown or unversioned recipes, ambiguous/invalid time windows, out-of-clip motion phases or SFX cues, unlicensed bound SFX, and intentional black without exact frames, reason, and approval policy.
- Deterministically map seconds to 24/30 fps using nearest-half-up frame conversion while retaining seconds as the authoritative timeline.
- Add clip/phase repair-task expansion, CLI/SDK/NDJSON parity, schema, 9:16 example, migration notes, synthetic render acceptance, and regressions without weakening existing hard gates.

## 0.9.16

- Add native Giggle text-to-audio dialogue generation through `listSpeechVoices`, `generateSpeech`, and `querySpeech` NDJSON methods plus matching CLI commands.
- Download generated speech atomically as MP3 with SHA-256 receipts and direct `Audio.Dialogue` track handoff metadata.
- Keep `GIGGLE_API_KEY` process-environment-only, remove signed provider URLs at public AgentCut boundaries, and mark generated speech non-release-eligible until media, timing, listening, and commercial-rights gates pass.
- Add schema, example, migration notes, and mocked network regressions.

## 0.9.11

- Add native Giggle instrumental BGM generation through `generateBgm` / `queryBgm` NDJSON methods and `bgm-generate` / `bgm-query` CLI commands.
- Read `GIGGLE_API_KEY` only from the process environment, redact signed download URLs at public interfaces, poll at provider-safe intervals, and publish downloads atomically with SHA-256 receipts.
- Mark generated music non-release-eligible until media, vocal, loop, loudness, listening, and commercial-rights gates pass; missing commercial-use metadata is an explicit release blocker.
- Preserve every 0.9.10 editing and validation capability and add schema, example, migration notes, and mocked network regressions.

## 0.9.10

- Add SHA-bound `CONDITIONAL_MACHINE_ADMISSION` for `NON_RELEASE_ROUGH_ASSEMBLY` only, preserving the original cadence FAIL and its machine-readable failure evidence.
- Require the current source SHA, preserved raw-review SHA, decision, confidence, selection reason, rollback point, replacement condition, and an explicit allow-list of rough-review-only failure codes; cross-check raw-review media SHA, status, and blocking failure multiset.
- Add explicit black/placeholder `timeline.holdSlots` that preserve runtime and suppress only their matching technical video gap while remaining release-blocking.
- Force release and final-visual validation to fail when any conditional source or unresolved hold remains; platform mutation stays unauthorized.
- Add schema, health, CLI/SDK/NDJSON/compile/render parity, migration notes, negative security regressions, and the real E28 CL2X-517 strict-media regression.

## 0.9.9

- Add a full-cut post-render hard gate combining pHash, aHash, and measured pixel motion at configurable sample rates while excluding the subtitle band by default.
- Reject unmotivated near-freeze clusters longer than four seconds and single-composition recurrence above two occurrences or six percent of a full-length timeline.
- Emit exact time clusters, hash/motion evidence, thresholds, implicated clips, and non-destructive rollback suggestions in a machine-readable report.
- Add CLI/SDK/NDJSON/render/renderMany parity, atomic failure behavior, health capability metadata, schema, examples, and real E28 V3 blind-spot regression coverage.

## 0.9.8

- Add a per-shot source-admission gate that reads each clip's actual cadence report, rejects cadence FAIL, and blocks `action_required` clips whose `near_duplicate_ratio` exceeds 0.15.
- Add strict `action_required`, `action_trajectory` (`windup/contact/force/result`), `source_reference_mode`, and `cadence_report_path` clip metadata contracts; block `single_still_only` action coverage by default.
- Add SHA-bound `release-validate` CLI/SDK/NDJSON review verification. Only an exact current-final SHA with full-cut `hard_gate_passed=true` can return `cleanRelease=true`.
- Keep `CONDITIONAL_MACHINE_ADMISSION` and every release result non-authoritative for platform mutation: automatic replacement is always false and explicit platform authorization remains external.
- Add real E27 N09/N04 rejection and N19 acceptance regressions plus pending-release render-manifest coverage.

## 0.9.7

- Add CL2X-358 canonical character-card prompt generation with a structured identity description and a fixed single-image 16:9 layout: far-left neutral front headshot followed by uncropped front/side/back full-body views.
- Add a hard admission validator for the real still image, required view roles/order, normalized bounds, evidence provenance, identity consistency, neutral production constraints, and every forbidden-content assertion.
- Integrate admitted cards into `ai_drama.continuity_asset_registry.v1` with deterministic manifest/image hashes, immutable identity locks, atomic writes, dry-run diffs, and silent-redesign rejection.
- Emit Seedance `[[char_n]]` bindings only after the same admission gate passes; add matching CLI and NDJSON methods, schemas, examples, capability metadata, and non-regression tests.

## 0.9.6

- Port CL2X-352/353 onto the accepted 0.9.5 CFR/black-frame/cadence/loudness/subtitle/narrative baseline without replacing any existing capability.
- Add `longTakePreflight` and `validateLongTake` NDJSON methods plus equivalent CLI commands and deterministic FFmpeg hard-cut timestamps.
- Add `generation_mode=image_to_video_first_last` with exactly one `start_frame` and one `end_frame`, an explicit `/api/v1/generation/image-to-video` receipt, and a hard prohibition on silent `omni-video`/`images[]` fallback.
- Add post-download continuity receipts retaining remote task ID, endpoint, input-role SHA-256 values, output SHA-256, and detected cuts; cadence/OCR/ASR remain separate gates.
- Add standalone CLI health with runtime/package identity while preserving the complete 0.9.5 NDJSON health capability map.
- Preserve the plan-level `requireCutReason` compatibility contract alongside the stricter 0.9.5 project continuity gate.

## 0.9.5

- Fix the 0.9.4 visible-tail cadence regression by removing `overlay` tail repetition and full-range `tpad` cloning.
- Express timeline PTS and handoff windows as exact integer-frame/fps rationals instead of shortened decimal timestamps.
- Add one out-of-range EOF sentinel frame per video clip; it advances FFmpeg framesync past the last allocated frame but is excluded by the half-open visibility range, so it cannot become visible padding or a freeze.
- Strengthen the hard-cut regression to the production release black-frame policy (`amount=95`, `threshold=32`) and add a moving-tail cadence preservation regression.

## 0.9.4

- Materialize video clip boundaries on the output constant-frame-rate grid using nearest-frame, half-up, half-open ranges; audio clip timing remains exact and unquantized.
- Clone a clip's final decoded video frame through its allocated visual frame range and use a half-frame overlay handoff guard so FFmpeg framesync cannot expose the black composition base at hard cuts.
- Emit each clip's `visualFrameRange` in compile summaries and expose the boundary strategy in NDJSON health.
- Add an end-to-end 24 fps regression that renders a deliberately non-frame-aligned hard cut and fails if FFmpeg detects an isolated pure-black frame.

## 0.9.3

- Replace render-time single-pass loudnorm with a measured two-pass master: render a headroom-protected lossless premaster, measure `input_i/input_tp/input_lra/input_thresh/target_offset`, then apply those values while copying the encoded video stream.
- Keep the declared loudness target, exact true-peak ceiling, clipped-sample limit, and duration gates unchanged.
- Render to same-directory staging files and atomically replace the destination only after all postflight gates pass; failures return nonzero, remove staging files, and preserve any prior output.
- Emit two-pass measurements and premaster attenuation in the manifest, expose the strategy in health/compile summaries, and clear stale failure reports only after a successful publish.
- Fix repackaged macOS wheels so bundled FFmpeg/FFprobe retain executable permissions.

## 0.9.2

- Fix the CL2X-282 semantic budget for short projects: the global ratio now applies only to semantic groups used more than once, because a single-use group cannot be repetitive.
- Keep duplicate, consecutive-use, and 12-second cooldown checks unchanged.
- Add configurable `narrativeGate.maxSemanticGroupRatio` (default `0.15`) and machine-readable semantic-budget coverage/health metadata.
- Add an E20 B03 regression for a 7.7-second, three-shot, three-semantic narrative segment.

## 0.9.1

- Activate the strict CL2X-298 `requireCutReason`/continuity preflight contract for CLI, SDK, renderMany, and NDJSON calls.
- Expose machine-readable runtime capabilities and required continuity metadata in NDJSON `health`.
- Add regression coverage proving missing cut reason/continuity metadata blocks compile while complete metadata passes.

## 0.9.0

- Add strict `requireBrandedOutro` release contract and machine-readable Nalu Motion coverage.
- Add outro brand/start/fit/audioPolicy fields and `AGENTCUT_NALU_MOTION_OUTRO_ASSET` injection.
- Fail validation/render when branded outro is missing, unreadable, incomplete, misplaced, cropped, or obscured by captions.

## 0.8.1

- Reserve configurable codec headroom (default 0.5 dB) below the declared release true-peak ceiling before AAC encoding.
- Keep postflight enforcement at the exact declared ceiling; no threshold relaxation.
- Add real AAC encode/decode true-peak regression coverage.

## 0.8.0

- Add source-peak, clip-gain, and overlap-aware projected clipping validation.
- Add required release master policy with loudness normalization/limiting and configurable true-peak ceiling.
- Measure and manifest integrated loudness, true peak, and full-scale decoded sample count; remove release renders that fail.

## 0.7.0

- Add deterministic, time-bounded per-video-clip `cleanupRegions` with delogo, mask, and regional blur modes.
- Reject frame/time bounds errors and caption-safe-band overlap unless explicitly allowed.
- Add cleanup source SHA, region/time/mode provenance and non-destructive rollback metadata to render manifests.

## 0.6.0

- Add explicit reusable Nalu Motion 9:16 outro/end-card support with registered `nalu-motion-v1` defaults.
- Append the outro after the main dialogue/subtitle boundary and emit SHA-bearing render manifests.
- Add hard validation for assets, template, transitions, safe area, dialogue/subtitle overlap, and outro audio peak safety.

## 0.5.1

- Add actual-write audio-save backend health checks before Demucs import, model download, or inference.
- Automatically patch Demucs saves to soundfile or FFmpeg when torchaudio has no working backend.
- Record input/model/output SHA-256 provenance plus created-file and backup rollback manifests.

## 0.5.0

- Ship CL2X-282 Narrative Gate with production metadata/runtimePolicy compatibility, stagnation, 12-second semantic cooldown, 15% global semantic budget, motivated cutaway, reaction-delta, background-bed, fallback/padding, and machine-readable coverage-gap gates.
- Add `dialogue-isolate` for deterministic local WAV vocal-candidate preparation with conservative contamination/artifact reporting and registration eligibility.

## 0.4.1

- Fix FFmpeg 8 audio timestamp overflow for trimmed clips with non-zero in-points by assembling clips per semantic track before mixing.
- Reject and remove renders whose audio stream start or duration differs from the project by more than 0.1 seconds.
- Deduplicate repeated media inputs and split decoded streams inside the filter graph for large timelines.
- Add an opt-in Narrative Gate for semantic repetition, no-information shots, cutaway relevance, background-bed budgets, and explicit required-shot coverage.

## 0.4.0 — 2026-07-17

- Added native `subtitleTracks` / Caption clips with Chinese text, timing, font, size, color, outline, alignment, margins, and wrapping.
- Added burned-in FFmpeg rendering for CLI, SDK, NDJSON `render`, and `renderMany`.
- Added the `requireBurnedSubtitles` P0 hard gate for missing captions, empty text, bounds, overlap, dialogue identity, font files, and font glyph coverage.
- Added expected dialogue coverage with one-to-one `dialogue_id` reconciliation and `40/40` machine-readable counts.
- Added a Chinese-font 9:16 safe-area example, schema, documentation, and end-to-end render tests.

## 0.3.0 — 2026-07-17

- Added deterministic timeline trim-plan transforms over stable clip/dialogue identifiers.
- Added synchronized multi-track A/V head trim and cross-track ripple editing without speed changes.
- Added protected and frozen clip/beat/dialogue/time-range guards plus locked-order checks.
- Added dry-run diffs, expected operation/total assertions, atomic writes, deterministic audit hashes, and exact rollback.
- Added CLI and NDJSON `transformProject`/`trimProject`/`rollbackProject` protocols and schemas.

## 0.2.0 — 2026-07-17

- Added strict FFprobe media validation through `validate` + `strictMedia` and `validateMedia`.
- Added matching-stream duration bounds checks, missing-stream checks, and final video coverage/black-gap diagnostics.
- Added optional clip `id` and `metadata`, retained in diagnostics and compile summaries.
- Made NDJSON render responses compact by default; added opt-in command and SHA-256 fields.
- Added opt-in NDJSON progress events for long renders.
- Parallelized unique-source FFprobe work for large projects.
- Added production black-gap, media-bounds, compact-response, progress, and identity regression tests.

## 0.1.0

- Initial two-video-track, three-audio-track FFmpeg editing engine and concurrent Agent protocol.
