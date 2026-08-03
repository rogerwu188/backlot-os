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

- **Review Agent 1.1.1** — shot, asset, and final-cut review for video, audio, and images; five-point scoring; bundled OCR; issue ledger; regression rules; NDJSON workers; AgentCut repair tasks.
- **Story Agent 0.2.1** — Claude >=4.8 policy, replaceable Claude/command model adapter, premium-streaming pacing gates, structured episode generation, deterministic script review, failed-only revision, and append-only rollback snapshots.
- **Producer/Supervisor Agent 0.2.0** — project planning, idempotent dispatch, Giggle image/video provider, evidence supervision, interruption recovery, failed-only retry, and per-episode/project cost aggregation.
- **Launcher 0.2.0** — one-screen multi-chapter novel import, automatic episode planning, source-density warning, five-agent hosts, local production workbench, credit ledger, and resumable pipeline start.
- **AgentCut 0.9.17** — timeline validation, compilation, rendering, shot recipes, dialogue/subtitle alignment, audio, and release gates.
- **Factory Runtime 2.0.20** — file-native queues, workers, dispatcher, supervisor, idempotency, receipts, rollback, and shared-message protocol.
- **Pipeline Tools** — production gates and orchestration utilities proven in the original production line.
- **Legacy compatibility prompts** — the original Qingshan agent prompts are retained as migration references, not as the BacklotOS product identity.

## Quick install

Requirements: macOS or Linux, Python 3.10+, Git, FFmpeg, and Node.js 20+.

```bash
git clone https://github.com/rogerwu188/backlot-os.git
cd backlot-os
./scripts/install.sh
./scripts/doctor.sh
```

The installer creates an isolated runtime and does not copy production media or credentials. Configure optional integrations in a local `.env`; never commit that file.

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
- [Contributing and update flow](CONTRIBUTING.md)
