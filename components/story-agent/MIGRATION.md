# Migration — installing on another machine (BacklotOS)

## 0.4.0

- Adds runtime-only `importNovel` and exact-count `planSeries` verbs.
- Adds append-only `continuityCheck` for known facts, adjacent weather, and hook pickup.
- Pacing policy 1.1 adds source-level dialogue ratio, dialogue-only run,
  action-scene dialogue, and visual-restatement gates.
- Package metadata and runtime version are now covered by a consistency test.
- Existing character-asset, combat, release-visual, failed-only, and rollback
  contracts remain in force; this is an additive merge, not a replacement.

## 0.1.1 acceptance hardening

- Model output now undergoes nested structural validation.
- Failed-only revision rejects deleted, added, or reordered siblings.
- External commands execute as argv without a shell and never expose stderr.
- Anthropic readiness requires the package, key presence, and an explicit model name.
- The optional ledger is append-only NDJSON and stores rollback snapshots.
- CLI capability failures return non-zero status; batch status reflects child failures.
- Canon/source-fidelity claims were narrowed to the checks actually implemented.

## 1. Copy the package
Copy `claude_story_agent/` to the target host. It is self-contained; core deps = stdlib.

## 2. Choose a model backend (for generation only; review needs none)
- **Anthropic**: `pip install -e ".[anthropic]"`, set `CLAUDE_STORY_MODE=anthropic`,
  put `ANTHROPIC_API_KEY` in the host secret store / real `.env` (never in this repo).
- **External command**: set `CLAUDE_STORY_MODE=command` and `CLAUDE_STORY_COMMAND` to a CLI
  that maps `{"system","user"}` (stdin JSON) → model text (stdout).
- **Offline/tests**: `CLAUDE_STORY_MODE=mock`.

## 3. Wire the host loop
Run the NDJSON server as a long-lived process; BacklotOS sends one JSON request per line:
`{"verb":"generate"|"review"|"revise"|"generateMany"|"reviewMany", ...}`.
Novel/series hosts may also send `importNovel`, `planSeries`, and `continuityCheck`.
`>=4` workers by default for the *Many verbs.

## 4. Map the old 青山 host-session behavior
| Old (Cowork session) | New (this package) |
|---|---|
| Claude writes in-session from prompt files | `generate` via adapter (model backend) |
| Supervisor pre-gate reads scripts + gates | `review` (deterministic) → `failed_only` |
| 派单/PROGRESS rounds | host calls verbs; `status`/`progress` returns ledger |
| project canon/观众已知清单 | passed in `spec.canon` / compat fixtures (de-identified) |

## 5. Project-specific compat
`compat/qingshan/` holds only de-identified fixtures and a mapping note, with no production source text.
Real project canon stays in the project repo and is passed at call time, never baked in.

## 6. Rollback
When `BACKLOT_STORY_LEDGER` is configured, every generate/revise appends an input/output SHA record and output snapshot (`VersionLedger`). To roll back, restore the snapshot whose `output_sha256` you want; the ledger never deletes. Without that variable, records last only for the current process.
