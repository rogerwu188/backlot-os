# Changelog

## Unreleased

## 0.2.50

- Migrate the governed series video route by episode: E40 and earlier remain
  on Seedance 2 Fast at 720p, E41-E44 use Seedance 2 Pro at 720p, and E45 onward
  use MiniMax-H3 at provider-native 768p. The paid manifest gate, provider
  capability registry, durable submitter, and low-level HTTP transport now
  agree on the registered routes while continuing to reject Mini, bare
  `seedance-2.0`, unknown models, and manifest-level policy expansion.
- Admit semantic grouped video units up to the provider's 15-second ceiling
  without weakening action tempo: every authored atomic window remains bounded
  to two seconds, or 1.2 seconds for fight/chase beats, with the existing onset,
  idle-gap, real-time playback, and terminal-result checks intact.
- Add regression coverage for E45 MiniMax-H3 admission, cross-episode model
  rejection, grouped semantic timing, and transport-level allowlist parity so a
  stale Fast-only client cannot silently block an otherwise valid paid batch.

## 0.2.49

- Make task-lane liveness scoped and fail-closed: RUNNING now requires a live
  owner lease plus progress and next-due timestamps, stale rows are excluded
  from active successors, and observation-only watchdogs cannot keep an
  unfinished episode falsely healthy. Continuous dispatch writes the initial
  bounded lease, with regression coverage for missing/expired leases, overdue
  progress, observation-only continuity, live producing work, and task-local
  remote waits.

## 0.2.48

- Correct the exact-first-frame continuity operand to compare decoded frame 0
  with decoded frame 1. Keep source-authority-to-frame-0 admission and every
  threshold unchanged, and expose authority-to-frame-1 only as a named,
  non-gating composite diagnostic. Regression coverage prevents provider
  frame-0 drift from being counted twice while preserving the hard rejection.

## 0.2.47

- Protect continuous scheduler state with a single-writer lease, exact-SHA
  compare-and-swap, conflict-time reload and disjoint `task_id` merge, plus
  crash-durable temp-file `fsync` and atomic rename. Same-task conflicts now
  fail closed, with a three-concurrent-writer regression preventing stale
  whole-file overwrites. CI and the installed-runtime doctor now verify both
  the dispatcher and its state-store dependency so a current GitHub version
  cannot conceal stale production scheduler code.

## 0.2.44

- Make the immutable release workflow install the declared media-review runtime before running exact-frame verification, matching pull-request CI and production dependencies.
- Remove the exact-frame gate's undeclared Pillow dependency and use the already-declared OpenCV runtime for decoded RGB authority hashing.

## 0.2.43

- Route every `EXACT_FIRST_FRAME` task through the provider's native image-to-video `start_frame` field; ordinary Omni `images[]` references can no longer satisfy this contract.
- Bind the source bytes and decoded pre-encode RGB authority into the durable submission transaction, then require a read-only harvested frame-0 and frame-0-to-frame-1 continuity gate.
- Forbid automatic one-frame prepend or replacement repair, preserve Fast-only 720p admission, and extend installed-runtime parity checks to the exact-frame submitter and QA gates.

## 0.2.42

- Reject provider/model resolution mismatches before any paid video POST; Giggle Seedance 2.0 Fast is now authoritatively limited to 720p or 480p.
- Compile Fast long-take prompts at provider-native 720p and require an explicit deterministic 1080p delivery transform instead of falsely labeling an upscale as native generation.
- Add regression coverage for the exact 1080p failure that caused a fully refunded E40 U01 request.

## 0.2.41

- Change the installed Producer/Supervisor Giggle provider default and model
  allowlist to `seedance-2.0-fast`; v0.2.40 already protected the paid gate and
  HTTP client, but the runtime health/default path still exposed the old bare
  identifier.
- Bump the Producer/Supervisor component to 0.2.2 and make `doctor.sh` fail
  unless the actually installed pipeline adapter reports Fast as its video
  default. This turns checkout/runtime agreement into an executable deployment
  assertion instead of a release-note claim.

## 0.2.40

- Enforce `seedance-2.0-fast` as the only production-allowed Seedance 2 video
  SKU at the real paid submission gate. A manifest cannot expand the policy to
  Pro, Mini, or the unpriced bare `seedance-2.0` identifier.
- Align long-take compilation and shot-package completion accounting with the
  same Fast-only policy, eliminating downstream gates that would accept the
  paid request and then reject the resulting clip for using Fast.
- Change the low-level Giggle HTTP client and generic episode compilers to Fast
  as well, with a client-level regression test proving Pro, Mini, and the bare
  model identifier cannot reach the network even if an upstream caller drifts.
- Keep provider capability verification fail-closed, so Fast must be both the
  production policy and a verified provider capability before any provider
  POST.
- Add regression coverage for Fast-only admission and attempted manifest-level
  policy expansion to the required CI path, preserving the installed runtime
  parity checks that prevent a newer GitHub checkout from concealing an older
  production gate.

## 0.2.39

- Add an installed provider-video capability registry and make the real paid
  video submission gate require a non-empty intersection between production-
  allowed models and provider-supported models before any provider POST.
- Record Giggle's current official Omni API model set (`seedance-2.0-pro` and
  `seedance-2.0-fast`) so a standard-only `seedance-2.0` manifest fails during
  zero-cost precheck instead of reaching the provider's unpriced-model error.
- Preserve the standard-only production policy: the new gate reports the
  empty intersection and does not silently substitute Pro, Fast, or Mini.

## 0.2.38

- Allow a paid image manifest to omit a scene reference only when the task is
  explicitly `asset_role_only=true`, binds exactly one verified character
  reference, forbids direct shot-start use, and carries complete owner/count/
  state plus reusable-scope controls. Ordinary shot images still require
  exactly one scene reference, so relabelling a character asset as a scene is
  not an accepted workaround.
- Preserve durable image-submit intent, task-ID binding, response-loss
  quarantine, and ledger-reconciliation behavior while adding regression
  coverage for the new reusable-asset validation branch.
- Make `doctor.sh` fail when the installed BacklotOS version or installed image
  submit tool differs from the checked source, preventing a newer Git checkout
  from concealing an older production runtime.
- Add an explicit `--project-root` to the image manifest submitter so installed
  BacklotOS can resolve another production repository's relative inputs,
  reports, and durable transaction directory without importing the module and
  mutating globals. The default root remains backward-compatible.

## 0.2.37

- Add a persistent, idempotent task-lane dispatcher that claims READY work as
  soon as a local slot opens. Shot deliverables outrank precompile work,
  task-local remote waits do not consume local capacity, argv commands never
  use a shell, and durable dispatch intents prevent duplicate execution after
  restart. Heartbeats are now watchdogs rather than the primary production
  driver.
- Compute episode throughput from admitted evidence instead of authored status
  labels. Prompt-only work is reported separately and contributes zero admitted
  seconds; a completed shot package requires exact canonical, manifest, first
  frame, ordered reference, applicable asset, dialogue, output, and QA SHA
  bindings under standard `seedance-2.0`.
- Reject false-idle schedulers that have unfinished dependency work but no
  READY, RUNNING, QA, task-local remote wait, or evidenced legal blocker with a
  bounded recheck time.
- Require VERIFIED_ZERO or a full refund before paid retry. After two failures
  in one failure family and representation, a third attempt must change prompt
  and input SHAs and carry validated evidence for shot splitting, transport
  change, deterministic compositing, or asset isolation.

## 0.2.36

- Make paid Giggle image submission durable and idempotent without reducing
  concurrency: atomically record per-task intents, bind returned task IDs,
  reuse exact completed fingerprints, and quarantine charged or unresolved
  response-loss cases before any retry.
- Replace the false `timeout = zero credits` assumption with bounded
  authoritative-ledger classification and separate newly submitted, recovered,
  and unmapped counts in batch receipts. Generation POSTs now use a dedicated
  180-second response timeout while remaining non-retrying at the HTTP layer.
- Reject image manifests that claim exact mask semantics when the selected
  provider endpoint transports the mask only as a visual reference image.
  Provider-native mask support must exist in the request payload before a
  SHA-bound `edit_mask` can authorize paid generation.
- Fail action-like prompts that omit `action_unit` and would previously bypass
  the performance-tempo gate. Require explicit atomic action windows, first
  fight/chase displacement by 0.5 seconds, combat beats no longer than 1.2
  seconds, and no unmotivated gap longer than 0.25 seconds before provider
  spend.
- Require standard Seedance 2.0 video models at submission, add fail-closed
  combat-coherence and source-corpus gates, register reusable wardrobe
  variants, isolate dependency waits to their own task lanes, and make local
  prompt-memory resolution portable across source and deployed layouts.

## 0.2.35

- Upgrade the Story Agent component to 0.4.0 by merging the verified Claude
  Writer handoff into the stricter BacklotOS mainline.
- Add runtime-only novel import, exact-count series planning, append-only
  continuity checks, and source-level dialogue pacing gates without weakening
  character asset, combat, release visual, failed-only, or rollback contracts.
- Add package/runtime version consistency coverage so a wheel cannot advertise
  one version while the imported agent reports another.
- Add a motivated combat-camera vocabulary with fifteen typed techniques bound
  to action beats, exact time ranges, subject anchors, axes, and narrative use.
- Allow richer short-shot storyboard grammar while limiting a 15-second action
  take to two dynamic camera segments separated by stable observation.
- Reject decorative camera stacking, mode mismatches, unsupported edit grammar,
  sustained shake, and slow motion without a decisive contact before paid
  generation.

## 0.2.34

- Add executable parallel QA fan-out to the Pipeline adapter with isolated
  failures, deterministic result ordering, optional atomic receipts, and a
  final aggregate barrier.
- Require visual, dialogue, OCR, identity, action-space, cadence, and credit
  checks to run concurrently once media is available, while preserving serial
  ordering only for genuinely dependent generation chains.
- Add concurrency, failure-isolation, advisory, validation, and receipt tests.

## 0.2.33

- Replace the blanket dialogue-glyph prohibition with three typed policies:
  audio-only isolation, exact diegetic text, and exact provider captions.
- Allow readable account pages, labels, letters, brush-writing close-ups, and
  provider captions when their exact text and source SHA are bound before
  generation and OCR plus human review are mandatory.
- Reject pseudo-writing, misspellings, unbound text, and duplicate provider plus
  AgentCut subtitle layers instead of rejecting every readable glyph.

## 0.2.32

- Require every Seedance dialogue reference segment to be 2-15 seconds; short
  verified speech may only be padded with trailing silence, never regenerated
  unchanged merely to satisfy transport limits.
- Add a visual-prompt dialogue isolation gate: exact spoken glyphs are carried
  by ordered audio assets and may not appear in the visual generation prompt,
  preventing model-burned captions from leaking into clean sources.
- Preserve intentional readable props and writing shots when they are bound to
  an approved text plate or deterministic AgentCut text layer; only invented,
  misspelled, or unbound model text is rejected.
- Require each generated spoken line to bind a typed expressive delivery
  contract covering psychology, emotion intensity, pace, pauses, emphasis,
  volume, breath, delivery transition, and synchronized body performance.

## 0.2.31

- Compile every spoken line from a typed psychology-and-prosody profile: inner
  state, emotion intensity, pace, pauses, emphasis, volume, breath, delivery
  transition, and synchronized body action. Preserve voice identity while
  rejecting an entire character performance with one repeated delivery signature.
- Require writer-completed, source-grounded character briefs and SHA-frozen visual/voice assets for the full actor roster before multi-keyframe video compilation.
- Extend the Story Agent episode schema and generation prompt so E39+ scripts must define asset-ready, era-grounded temporary characters before any downstream generation.
- Block temporary random characters, unapproved historical or same-episode face/wardrobe/voice similarity, and within-shot identity or wardrobe drift.
- Replace prose-only fight direction with a fail-closed timed choreography
  contract: every exchange names the initiator, target, contact point, force
  direction, footwork, reaction, and terminal state.
- Require distinct SHA-bound identity references, wardrobe silhouettes, face
  geometry, and first-second displacement for every combat participant.
- Scope action-reference video inheritance to timing and body mechanics only,
  and hard-lock the winner, restrained actor, and terminal identity hold.
- Treat combat identity/outcome inversion and visible-actor freezing as hard
  long-take failures even when the aggregate score is at least 60.
- Release AgentCut 0.9.22 with release gates that reject blur/defocus repair
  sources and unapproved opaque subtitle boxes.

## 0.2.30

- Add a typed dialogue-mode compiler gate: visible native speech, deliberate
  closed-mouth voice-over, and no-dialogue units are mutually exclusive.
- Reject prompts that combine on-camera dialogue with silent-performance or
  post-dub language, and require a bound audio reference for visible speakers.
- Record E38's silent-repair/old-audio binding risk as a pending local-LoRA
  defensive rewrite; assembly metadata may no longer claim unverified lip sync.
- Add geometry-and-persistence OCR adjudication so face-sized texture false
  positives remain evidence without hiding persistent audience-readable text.
- Add bounded, time-scoped generated-text cleanup for zero-credit source repair
  before exact-SHA rebinding and final OCR validation.

## 0.2.29

- Add a prompt-literal glyph scan for text-layer-post-only shots. Exact dialogue,
  labels, medicine names, people, places, and account strings must be replaced
  by opaque prop IDs before visual generation and added later in AgentCut.
- Record the E38 drawer-label echo as a pending local-LoRA defensive rewrite;
  a zero-credit cleanup is evidence, not a claimed positive regeneration.
- Treat an absent OCR allow/deny lexicon as advisory when no readable text is
  detected, while preserving hard failures for Latin text and multi-Han runs.
- Add a reusable generated-label cleanup tool for already-paid source recovery.

## 0.2.28

- Add an admitted E38 video-prompt memory for held foreground poses and
  looping or frozen supporting actors in multi-character action shots.
- Require a visible-actor motion ledger with per-actor paths, interactions,
  terminal positions, and sub-second displacement checks before submission.
- Reject gesture loops, expression-only motion, background freezes, and
  repeated-frame duration filling at prompt compilation time.

## 0.2.27

- Add an admitted E38 image-prompt memory showing that re-injecting a full
  identity-reference set after an accepted predecessor can duplicate actors.
- Require the accepted predecessor to become the sole state authority for the
  next action image, with exact roster, wardrobe-count, and unique role locks.

## 0.2.26

- Add portable E38 prompt-failure memories for generated prop pseudo-text,
  model-burned dialogue captions, and oversized action effects caused by
  missing ordered state-authority keyframes.
- Keep new failure/rewrite records explicitly pending until a positive repair
  passes OCR or action-scale QA; pending lessons may block known-bad prompt
  patterns but cannot claim a learned successful result.
- Require generated documents and labels to use blank material plates with
  real-font text added in AgentCut, and decouple exact dialogue text from the
  visual generation prompt.

## 0.2.25

- Require a complete actor roster and per-keyframe motion coverage for every
  Seedance 2 multi-keyframe long take before paid generation.
- Reject visible actors described only with static holding language; each must
  have continuous micro-action, event reaction, and at least two motion cues.
- Require an explicit reason when a rostered actor leaves the frame so
  background performers cannot silently freeze or disappear.
- Require a separate visible-actor motion score for multi-character long takes;
  a moving foreground can no longer conceal frozen supporting performers.
- Align AgentCut's legacy setup entrypoint with its 0.9.20 runtime and
  `pyproject.toml` metadata, with a regression test preventing version drift.

## 0.2.24

- Extend the replacement-binding release gate across live video, audio, and
  recursively nested clip metadata so repaired projects cannot retain a
  superseded source path or SHA outside the visible source field.
- Reject accidental overlaps between enabled clips on the same timeline track
  while preserving intentional composites and mixes on separate tracks.
- Release AgentCut 0.9.20 with regression coverage and a migration guide for
  deterministic repair binding and timeline-overlap cleanup.

## 0.2.23

- Replace workstation-to-GitHub prompt-memory pushes with a collector-first
  default: production nodes hold no GitHub or S3 credentials.
- Add an authenticated central LoRA Memory Hub that validates submissions,
  writes content-addressed S3 objects, and periodically converges them to GitHub.
- Ship a reproducible Docker deployment, durable node-side retry queue, and an
  explicit credential-boundary guide; retain direct Git sync only as a
  development override.

## 0.2.22

- Enable privacy-filtered LoRA prompt-memory synchronization by default on every installed workstation.
- Persist admitted local samples across upgrades and failed uploads, retry automatically before later prompt compilation, and serialize concurrent sync attempts.
- Discover or create an isolated Git checkout for synchronization while preserving explicit checkout and remote overrides.
- Record local sync receipts without credentials, private evidence paths, or episode media.

## 0.2.21

- Add an exact replacement-binding hard gate. A repaired clip must point to the
  admitted replacement file SHA, carry matching source metadata, and cover every
  declared target before compile, render, final-visual approval, or release.
- Reject superseded source SHAs and path signatures anywhere in the enabled
  video timeline, with an exact residual clip list for deterministic repair.
- Add portable, privacy-filtered local LoRA memory synchronization so admitted
  prompt-learning samples can converge across configured BacklotOS machines.

## 0.2.18

- Add a terminal-support prompt contract for gravity-stable result holds.
- Reject raised-foot, suspended, or airborne transition poses when a provider
  minimum-duration clip would stretch them into artificial slow motion.
- Propagate terminal-support contracts from the action causal-chain compiler to
  the paid-generation prompt gate.

## 0.2.17

- Preserve action-prop function classes during prompt optimization so footprint
  corrections cannot turn grounded environmental structures into handheld or
  floating substitutes.
- Add relational physical-scale, one-visible-causal-phase, and non-intersecting
  multi-actor movement-lane gates before paid generation.
- Add an exact-tail action causal-chain compiler: dependent phases run serially,
  while unrelated generation, polling, and QA remain parallel.

## 0.2.16

- Add a first-class immutable release-archive installation guide for third-party users.
- Document SHA verification, archive provenance, archive updates, and immediate rollback.
- Clarify that `scripts/update.sh` applies to Git checkouts while archive installations replace verified release packages.

## 0.2.15

- Move CI and release workflows to the current Node.js 24-based official GitHub Actions releases.
- Remove the Node.js 20 action-runtime deprecation warning from maintained workflows.

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
