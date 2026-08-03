# Claude Producer/Supervisor Package Request

Claude should implement and return the missing BacklotOS producer/supervisor and production-semantic adapters against this source snapshot.

Required package: `backlotos-producer-supervisor-agent`.

Required command adapters:

- `BACKLOT_PRODUCER_COMMAND`
- `BACKLOT_PIPELINE_COMMAND`

The implementation must provide runnable source, schemas, CLI, NDJSON and HTTP interfaces, append-only state and credit ledgers, idempotent dispatch, progress/status, resume, failed-only retry, tests, package hashes, and a handoff receipt. Unsupported capabilities must remain explicit and must never be reported as passing.

The package must not contain credentials, project-specific novel text or media, and must not publish, delete, or overwrite platform content. Online workflow scope excludes copyright processing.

Use `README.md`, `docs/ARCHITECTURE.md`, `contracts/`, `components/launcher/`, and `deploy/five-agent/` as the authoritative integration contract. Return a patch or complete changed-file archive when the sandbox cannot push to GitHub.
