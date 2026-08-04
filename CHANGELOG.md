# Changelog

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
