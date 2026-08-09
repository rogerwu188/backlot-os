# BacklotOS

**An agentic operating system for AI-native film production.**

BacklotOS turns a novel into a governed production workflow: source intake, writing, visual planning, media generation, editorial assembly, and evidence-backed review. It is designed for ordinary creators, local workstations, and cloud workers, with deterministic contracts, exact-media provenance, rollback records, and human approval before irreversible release actions.

## Start with one screen

After installation, run:

```bash
backlotos start
```

A local production workbench opens. Its dashboard lists every project and every
episode across story, script review, visual planning, media generation, editing,
and final review. It also shows append-only estimated, consumed, refunded, and
net credit totals per episode and for the full project; missing provider cost is
shown as `NOT_REPORTED`, never as free. State is recovered from disk after restart. Select **New
production** and provide only:

1. A novel URL or uploaded TXT, Markdown, HTML, PDF, EPUB, or DOCX file.
2. Short drama or long drama.
3. Live action or animation.
4. Total episode count (short-drama default: 200; long-drama default: 40).
5. Episode duration and 9:16 or 16:9 aspect ratio.

Confirming the form stores an immutable source copy and SHA provenance, checks
source-to-runtime density, creates every episode specification, and starts the
Story Agent queue. The default writing contract uses fast US premium-streaming
pacing: immediate conflict, compressed dialogue, no recap or filler, escalating
turns, and a consequential end hook. If a model backend is not configured, the
project remains resumable in `WAITING_FOR_MODEL` instead of fabricating output.

## What is included

- **Review Agent 1.2.0** — shot, asset, and final-cut review for video, audio, and images; five-point scoring; bundled OCR and StoryClaw GPT‑5.5 vision adapter; issue ledger; regression rules; NDJSON workers; AgentCut repair tasks.
- **Story Agent 0.4.0** — Claude >=4.8 policy, replaceable Claude/command model adapter, runtime novel import, exact-count series planning, append-only continuity, premium-streaming 1.1 dialogue pacing gates, structured episode generation, deterministic script review, failed-only revision, and rollback snapshots.
- **Producer/Supervisor Agent 0.2.0** — project planning, idempotent dispatch, Giggle image/video provider, evidence supervision, interruption recovery, failed-only retry, and per-episode/project cost aggregation.
- **Launcher 0.2.0** — one-screen multi-chapter novel import, automatic episode planning, source-density warning, five-agent hosts, local production workbench, credit ledger, and resumable pipeline start.
- **AgentCut 0.9.20** — timeline validation, compilation, rendering, shot recipes, recursive video/audio replacement binding, same-track overlap rejection, dialogue/subtitle alignment, audio, and fail-closed release contracts.
- **Factory Runtime 2.0.20** — file-native queues, workers, dispatcher, supervisor, idempotency, receipts, rollback, and shared-message protocol.
- **Pipeline Tools** — production gates, parallel orchestration, and privacy-filtered cross-machine prompt-memory convergence proven in the original production line.
- **Legacy compatibility prompts** — the original Qingshan agent prompts are retained as migration references, not as the BacklotOS product identity.

## Quick install

Requirements: macOS or Linux, Python 3.10-3.12, Git, FFmpeg, and Node.js 20+.

### Stable release archive (recommended)

Download the immutable public package without cloning repository history:

```bash
curl -L -o backlotos-v0.2.25.tar.gz \
  https://github.com/rogerwu188/backlot-os/releases/download/v0.2.25/backlotos-v0.2.25.tar.gz
expected_sha=$(curl -fsSL \
  https://api.github.com/repos/rogerwu188/backlot-os/releases/tags/v0.2.25 | \
  python3 -c 'import json,sys; print(next(a["digest"].split(":",1)[1] for a in json.load(sys.stdin)["assets"] if a["name"] == "backlotos-v0.2.25.tar.gz"))')
actual_sha=$(shasum -a 256 backlotos-v0.2.25.tar.gz | awk '{print $1}')
test "$actual_sha" = "$expected_sha"
tar -xzf backlotos-v0.2.25.tar.gz
cd backlotos-v0.2.25
./scripts/install.sh
./scripts/doctor.sh
```

The verification step reads GitHub's published asset digest and stops before extraction on any mismatch. The archive installer records `source-archive:v0.2.25` provenance even though release archives intentionally contain no `.git` directory.

### Git checkout (contributors)

```bash
git clone https://github.com/rogerwu188/backlot-os.git
cd backlot-os
./scripts/install.sh
./scripts/doctor.sh
```

The installer creates an isolated runtime and does not copy production media or credentials. Configure optional integrations in a local `.env`; never commit that file.

Every installation enables portable prompt-memory synchronization. Admitted
failed-prompt/rewrite/pass samples are stripped of local paths and credentials,
persisted through offline periods, and sent to an authenticated central
collector. Production machines never need GitHub or S3 credentials. The hub
writes content-addressed objects to a shared private S3 area, validates and
deduplicates them, then periodically pushes the deterministic corpus from the
only GitHub-authorized service. Upload failures remain queued and visible in a
local receipt. This shares the LoRA-ready training corpus and deterministic rule
adapter, not private episode media or unverified binary model weights. See the
[LoRA Memory Hub deployment guide](deploy/lora-memory-hub/README.md).

On StoryClaw, the host-managed GPT runtime is used by the Agents and no separate
`OPENAI_API_KEY` is required. `doctor.sh` detects that environment and reports
the key as `NOT_APPLICABLE`. A standalone command-line visual worker remains a
separate capability and must have an exact-SHA command bridge configured; the
health report keeps that boundary explicit instead of claiming a false PASS.
RapidOCR is bundled in the isolated installation and is discovered
automatically; StoryClaw users do not need to configure a separate OCR Python.

Provider defaults are Giggle `gpt2img` for images and `seedance-2.0-pro`
(Seedance 2) for video. The Story Agent requires a configured Claude 4.8-or-
newer model. Actual provider/model IDs are recorded in receipts; credentials
are accepted only through deployment environment variables.

## Pre-generation action and music contracts

Action shots are compiled before provider submission. The compiler reads every
earlier related action prompt, rejects repeated action pictures, checks actor
ownership and screen direction, and requires physically possible entry/contact/
result/exit states. Multi-actor shots additionally require named, non-intersecting
movement corridors and real-world lateral clearance before provider submission.
Dependent action chains remain sequential; the dispatcher
admits only one ready shot per chain and requires the exact accepted predecessor
tail as the next shot's first provider image. Identity and composition-only
references are not counted as temporal anchors. Unrelated shots remain parallel.
The supervisor uses dependency lanes rather than an episode-wide batch barrier:
each exact-tail chain advances one ready head at a time, while all independent
shots and other chains submit together. Remote polling runs in parallel, and
completed outputs are downloaded and QA-checked in bounded parallel workers.

Combat camera language is selected by action purpose, not sampled as visual
decoration. Storyboards may combine up to five motivated short-shot techniques;
a 15-second continuous action take allows at most two dynamic camera segments
with a stable reading interval between them. Every segment binds an action beat,
time range, subject anchor, axis relation, and narrative purpose. Unplanned time
defaults to a locked camera, so tracking, arcs, pushes, pulls, cranes, shake, and
slow motion cannot accumulate into continuous drift.

Combat contracts also require one of fourteen causal continuity ladders. It binds ordered
action beats to persistent contact, environment, recovery, damage, formation,
prop, or distance evidence and closes on one relational composition. The
resolving camera must be one of the motivated segments already declared in the
camera plan. The embodied-topology method additionally requires load-bearing
geometry, ordered footholds or grips, distinct contacts, and a measured landing
relation when a fighter traverses a larger body or structure. This licensed Hell
Grind integration also supports a committed-miss counter window: the defender
must visibly clear the attack line, the weapon must remain trapped in measured
terrain contact, and the counter may start only after the extraction delay is
readable. It is explicitly a
portable prompt/rule adapter; it does not claim Seedance model-weight training.
The near-miss armor-interception method separately proves measured body
clearance, glancing protection contact, an unharmed body state, persistent armor
damage, and opposed recovery costs, preventing a partial interception from
collapsing into either a clean miss or unexplained body damage.
The force-conversion method additionally preserves a defender's prop, body
orientation, measured displacement, landing absorption, and residual stance
cost when a blocked heavy impact becomes controlled aerial recovery.
The follow-through exposure method preserves the opponent's committed recovery
state, measures gap closure to a named target zone, proves embedded penetration
before extraction, and carries the promoted wound state into the closing frame.

When several short clips cannot preserve one continuous physical event, use
`multi_keyframe_long_take` instead of adding more edit seams. This mode compiles
one 15-second Seedance 2 Pro Omni generation from 3-9 ordered, SHA-bound
keyframes. Every reference declares its exact role, inherited state, forbidden
inheritance, actor blocking, unique action state, camera side, position, and
facing. Adjacent camera paths must be physically reachable within their time
window; impossible axis flips, speed, or aperture crossings fail before paid
generation. A room-to-street change is
accepted only through one named `SAME_APERTURE_CROSSING`; teleporting, action
resets, slow motion, and unmotivated sway/orbit/roam fail before provider spend.
The compiler also ships with a local LoRA-ready prompt-failure dataset. It
precompiles admitted failure lessons into every long-take prompt and records the
dataset SHA and sample IDs, so another workstation reproduces the same learned
guardrails without private media. Long takes pass at 60 points unless identity,
safety, era, OCR, or media-integrity hard failures override the score.
Image-generation failures use the same memory path. Generated papers, drawer
labels, documents, and signs are blank material plates; exact text is added by
AgentCut with a real font. A newly observed failure may enter the shared corpus
as `ACTIVE_REWRITE_PENDING_POSITIVE` so every node can reject the known-bad
pattern, but it becomes `ADMITTED` only after the rewritten image or video and
its applicable QA receipt are SHA-bound and pass.
Configure `max_submit_workers`, `max_poll_workers`, and `max_qa_workers` when a
provider or workstation needs lower concurrency.

Provider submissions remain parallel but are now transaction-safe. Before each
paid generation POST, BacklotOS atomically records a task fingerprint and submit
intent. A returned provider task ID is durably bound before polling starts. If
the response is lost, BacklotOS checks the authoritative credit window and marks
only that task as verified uncharged, charged-with-missing-ID, or unresolved;
it never assumes that a timeout was free. Exact fingerprints with a bound task
ID are resumed without another POST, while charged or unresolved submissions
are quarantined until the provider history restores their task ID. Other
submissions, downloads, and QA workers continue concurrently.

Every atomic action also carries an authored assembly window. The release
builder preserves native real-time speed, keeps only the designed action plus
result hold, and discards any unused provider minimum-duration tail. Long
dialogue or evidence units use stable compositions with motivated hard cuts;
continuous camera drift is rejected as a substitute for shot design.
Period-specific props, creatures, and constructed characters can additionally
declare a `period_entity_material_contract`. Before submission, the gate checks
that the final provider prompt contains the required historical materials and
explicitly rejects incompatible modern forms, then verifies the terminal visual
reference against its recorded SHA. Missing terms or a changed reference fail
closed before credits are spent.
Run the bundled example:

```bash
python components/pipeline-tools/action_prompt_pipeline_cli.py \
  --manifest components/pipeline-tools/examples/action_prompt_pipeline/episode_action_batch.json \
  --output-dir /tmp/backlotos-action-prompts
```

Release episodes must also declare a provenance-bound BGM contract and contain
real `Audio.BGM` clips. The BGM gate rejects silent stems, unverified sources,
wall-to-wall scoring, missing ambience-only windows, and music that masks
dialogue. See the [action and BGM production guide](docs/ACTION_PROMPT_PRODUCTION_GUIDE.md).

## Layout

```text
components/
  agentcut/          Timeline compiler and renderer
  story-agent/       Story generation and deterministic script review
  producer-supervisor-agent/ Production planning, supervision, dispatch, recovery, cost control
  launcher/          One-screen novel intake and production launcher
  review-agent/      Multimodal QA and repair-task generator
  factory-runtime/   Queue, worker, supervisor, and receipt runtime
  pipeline-tools/    Production orchestration and quality gates
  agent-factory/     Agent persona and operating templates
contracts/           Cross-component contracts (introduced incrementally)
legacy/              Original project compatibility material
scripts/             Install, update, doctor, verification, and publishing
.github/workflows/   CI and release automation
```

## Safety model

- Source code is versioned; media, QA evidence, credentials, ledgers, and runtime state are excluded.
- Review and repair-task generation are read-only by default.
- Publishing, deletion, login challenges, and irreversible platform operations always require explicit human authorization.
- Exact SHA provenance is preserved across evidence, timelines, and review results.

## Updating

```bash
./scripts/update.sh
```

Repository changes are developed on `agent/*` branches, validated in CI, and merged through pull requests. Version tags create immutable release artifacts; production machines update only when explicitly instructed.

`scripts/update.sh` is for Git checkouts because it verifies the remote and dirty-worktree state before changing versions. Archive installations update by downloading and verifying the next immutable release archive, then running its installer against the same `BACKLOT_INSTALL_DIR`. Keep the previous archive until the new `doctor.sh` run passes so rollback remains immediate.

For the Codex local test workspace, run `./scripts/enable-codex-github-sync.sh`
once. Every subsequent development-branch commit is automatically pushed to
the same GitHub branch and updates its PR. `main` remains CI/PR protected.
`scripts/update.sh` refuses dirty worktrees and unexpected origins, and the
installer records the exact Git commit used by the local runtime.

## Five isolated Agents

Cloud deployment runs five services with separate responsibilities and health
endpoints: producer/supervisor, story creation/review, production pipeline,
AgentCut post-production, and review/release preflight. The browser workbench is
a control plane and is not counted as an Agent. See
[`deploy/five-agent`](deploy/five-agent/README.md).

The producer/supervisor implementation and the semantic production-pipeline
adapter are delivered as an installable, tested source package
(`components/producer-supervisor-agent`, console scripts
`backlotos-producer-command` / `backlotos-pipeline-command`;
local package status `SUPPORTED_LOCAL_INSTALL`; see its
`HANDOFF_RECEIPT.json`). The official installer and five-Agent image install
the package. Live media generation is provided by Giggle and reports
`ADAPTER_REQUIRED` until `GIGGLE_API_KEY` is configured. The Compose stack still requires deployment-level
acceptance before it can be called production-supported. Existing prompts are
not presented as working code.

## Compatibility note

Some Python module and JSON contract names still use `qingshan_*` for backward compatibility with existing installations. Product-facing naming is BacklotOS; those identifiers will be migrated only through versioned compatibility releases.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Security and repository boundaries](docs/SECURITY.md)
- [Source inventory](docs/SOURCE_INVENTORY.md)
- [Action prompts and selective BGM](docs/ACTION_PROMPT_PRODUCTION_GUIDE.md)
- [Contributing and update flow](CONTRIBUTING.md)
