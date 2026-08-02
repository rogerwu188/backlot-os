# BacklotOS

**An agentic operating system for AI-native film production.**

BacklotOS turns a story into a governed production workflow: writing, visual planning, media generation, editorial assembly, and evidence-backed review. It is designed for local workstations and cloud workers, with deterministic contracts, exact-media provenance, rollback records, and human approval before irreversible release actions.

## What is included

- **Review Agent 1.1.0** — shot, asset, and final-cut review for video, audio, and images; five-point scoring; issue ledger; regression rules; NDJSON workers; AgentCut repair tasks.
- **Story Agent 0.1.1** — replaceable Claude/command model adapter, structured episode generation, deterministic script review, failed-only revision, and append-only rollback snapshots.
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

## Layout

```text
components/
  agentcut/          Timeline compiler and renderer
  story-agent/       Story generation and deterministic script review
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
- Publishing, deletion, copyright decisions, login challenges, and irreversible platform operations always require explicit human authorization.
- Exact SHA provenance is preserved across evidence, timelines, and review results.

## Updating

```bash
./scripts/update.sh
```

Repository changes are developed on `agent/*` branches, validated in CI, and merged through pull requests. Version tags create immutable release artifacts; production machines update only when explicitly instructed.

## Compatibility note

Some Python module and JSON contract names still use `qingshan_*` for backward compatibility with existing installations. Product-facing naming is BacklotOS; those identifiers will be migrated only through versioned compatibility releases.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Security and repository boundaries](docs/SECURITY.md)
- [Source inventory](docs/SOURCE_INVENTORY.md)
- [Contributing and update flow](CONTRIBUTING.md)
