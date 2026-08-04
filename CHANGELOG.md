# Changelog

## 0.2.14

- Select only Python 3.10-3.12 during installation because the bundled OCR dependency does not yet support Python 3.13+.
- Fail early with an actionable version message instead of failing late during dependency resolution.
- Add regression coverage for supported and unsupported Python runtimes.

## 0.2.13

- Make `scripts/install.sh` work from the downloadable GitHub release archive, where `.git` metadata is intentionally absent.
- Preserve exact commit and remote metadata for Git checkouts while writing deterministic versioned metadata for source archives.
- Add regression and CI archive smoke coverage for third-party installation.

## 0.2.12

- Restore the original `tools.<module>` import contract in standalone public
  archives without duplicating the executable pipeline modules.
- Run the action-design, spatial-physics, prompt-memory, direction, ownership,
  camera-space, and action-density root-cause gates in GitHub Actions.
- Prevent a narrow green CI subset from hiding broken third-party imports in
  the action prompt production tests.

## 0.2.11

- Add a fail-closed authored action-window contract so provider minimum-duration
  tails are discarded after the designed real-time action and result hold.
- Reject assembly speed changes, oversized action windows, retained unauthored
  tails, and invalid duplicate-frame policies before paid submission.
- Require long dialogue, evidence, and exposition units to use fixed composition
  plus a motivated hard cut, reaction cut, or evidence insert instead of
  continuous camera drift.

## 0.2.10

- Add a fail-closed period/entity material contract to the pre-generation
  prompt gate. Required construction terms and forbidden modern-form terms must
  be present in the final provider prompt before any paid submission.
- Bind the designed terminal reference image and its SHA to the same contract,
  preventing a period prop or creature from drifting into robots, armor,
  mechanical joints, or other incompatible silhouettes.
- Add regression tests for missing prompt constraints and changed reference
  images so these defects are blocked at prompt compilation, not deferred to QA.

## 0.2.9

- Add dependency-lane scheduling: submit every independent task and one ready
  head from each exact-tail action chain in the same concurrent wave.
- Run remote polling and completed-output download/QA concurrently with explicit
  worker limits, while preserving ordered tail-to-head generation within each
  individual action chain.
- Record selected and deferred task keys in each receipt so concurrency choices
  are auditable and resumable without an episode-wide batch barrier.
- Make exact-tail extraction retry frame-safe offsets and reject empty FFmpeg
  output, preventing a valid predecessor from silently stalling its successor.

## 0.2.8

- Exclude composition and ownership references marked `REFERENCE_ONLY` from
  temporal anchor counts and adjacent-keyframe interpolation requirements.
  This keeps those references available to the provider without falsely
  inflating the designed action-state chain or blocking a valid paid submit.
- Add regression coverage for a two-state tail-to-terminal chain carrying
  separate ownership-composition and identity references.

## 0.2.7

- Rebind a newly accepted predecessor tail into both provider reference fields,
  replacing the generic temporal anchor while preserving identity and other
  non-temporal references. This makes automatic chain activation satisfy the
  exact-tail submission gate introduced in 0.2.6.

## 0.2.6

- Make tail-chained action generation fail closed: only one ready shot per
  continuity chain may be submitted, and every dependent shot must use the
  materialized exact accepted predecessor tail as its first provider image.
- Keep unrelated shots parallel while serializing only their own continuity
  chain, and separate temporal anchors from identity, style, scene, and
  composition-only references during dynamic anchor-count validation.
- Add regression coverage for valid exact-tail handoffs and rejection of
  simultaneous or generic-start chain submissions.

## 0.2.5

- Add a normal-speed spectral masking gate for release BGM. Dialogue cues now
  require an equivalent no-BGM baseline, a 12 dB dialogue-to-music speech-band
  margin, bounded mean/peak increases, and smooth touching-cue role handoffs.

## 0.2.4

- Add a deterministic action-prompt optimizer that reads every earlier related
  action task, rejects repeated visual action signatures, compiles positive
  real-time/causality/ownership/spatial clauses, and binds its receipt to the
  final prompt SHA before paid generation.
- Add entry-and-planned-exit spatial feasibility contracts for collision
  corridors, limb paths, effect footprint/depth, protected props, occlusion,
  feedback order, and next-shot handoff poses.
- Add a portable action-prompt CLI, runnable example, operator guide, CI tests,
  installer health checks, and pipeline Agent instructions.
- Make release BGM fail closed: require generated-or-verified provenance, a real
  audible stem, selective narrative cue roles, dialogue ducking, and at least
  eight seconds of ambience-only space; reject wall-to-wall score beds.

## 0.2.3

- Add a fail-closed action-shot design gate before paid provider submission: one
  primary contact, bounded information and camera motion, fixed action axis,
  readable force/result state, exact cross-shot handoff tokens, and SHA-bound
  provider-prompt compilation.
- Upgrade AgentCut to 0.9.18 so explicit release projects cannot compile,
  validate, or render without complete burned subtitles, expected dialogue IDs,
  the Nalu Motion branded outro, and a required full-cut visual review gate.
- Add a SHA-bound release-branding pipeline gate for final-media preflight.

## 0.2.2

- Add a bundled StoryClaw Chat Completions image-analysis adapter with GPT‑5.5
  default routing, exact candidate SHA binding, strict JSON normalization, and
  environment-only credential loading.
- Auto-select the adapter when `BACKLOT_STORYCLAW_API_KEY` is available; retain
  `CAPABILITY_FAIL` when neither it nor an explicit command adapter exists.

## 0.2.1

- Detect StoryClaw/OpenClaw hosted runtimes in `doctor.sh`.
- Treat `OPENAI_API_KEY` as `NOT_APPLICABLE` when the host manages the GPT model.
- Report the unattended image-analysis command bridge separately from the host
  Agent's multimodal session, avoiding both duplicate-key prompts and false PASS.
- Add runtime-profile unit and doctor integration coverage.
- Bundle RapidOCR/ONNX/OpenCV with the Review Agent, prefer its isolated Python
  automatically, and retire the separate OCR-Python prompt for normal installs.

## 0.2.0 - Unreleased

- Added a one-screen local production console and `backlotos` CLI.
- Added a persistent workbench with background source-import progress, per-project and per-episode pipeline monitoring, and disk recovery.
- Added five isolated HTTP Agent hosts and a Compose deployment for producer, story, pipeline, post-production, and review/release-preflight roles.
- Added Producer/Supervisor Agent 0.2.0 with idempotent dispatch, evidence supervision, real progress, recovery, failed-only retry, credit aggregation, NDJSON/HTTP protocols, and fail-closed human authorization boundaries.
- Added a Giggle image/video adapter with environment-only credentials, task reconciliation, `gpt2img` image default and `seedance-2.0-pro` video default; it remains explicitly `ADAPTER_REQUIRED` without a configured key.
- Added multi-page novel directory crawling with same-book scoping, formal-directory ordering, retry/backoff, deduplication, page-level SHA provenance, and partial-source blocking.
- Added safe public-URL intake plus TXT, Markdown, HTML, PDF, EPUB, and DOCX upload support.
- Added immutable source copies, exact SHA provenance, append-only events, automatic episode plans, and resumable Story Agent queues.
- Added short/long drama, live-action/animation, total episode count, episode duration, and aspect-ratio inputs with ordinary-user defaults.
- Added source-density warnings that prohibit runtime padding.
- Added append-only per-episode and project credit accounting with provider task/evidence references, refunds, provisional/final status, and workbench totals.
- Upgraded Story Agent to 0.2.1 with a fail-closed Claude >=4.8 model policy, fast US premium-streaming pacing prompts, and deterministic opening-hook, end-hook, repeated-dialogue, dialogue-density, and non-advancing-shot checks.
- Added opt-in local Codex post-commit GitHub branch synchronization and installed-commit provenance.

## 0.1.0 - 2026-08-02

- Initial BacklotOS monorepo foundation.
- Imported Review Agent 1.1.0 and AgentCut 0.9.17 source.
- Integrated Story Agent 0.1.1 with strict output validation, failed-only topology protection, safe model adapters, and append-only rollback snapshots.
- Imported the file-native Factory Runtime 2.0.20.
- Added source-only production tool compatibility layer.
- Added portable installation, health checks, upgrades, CI, and secret/media guards.
- Added cross-platform AgentCut subtitle-font configuration without relaxing font or glyph validation.
