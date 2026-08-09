# Deployment

## Workstation

Run `./scripts/install.sh` from either a verified release archive or a Git checkout. By default, the isolated runtime is installed under `$XDG_DATA_HOME/backlotos` or `~/.local/share/backlotos`. Override it with `BACKLOT_INSTALL_DIR`. Release archives intentionally contain no `.git` directory; the installer records deterministic `source-archive:v<version>` provenance instead.

## Configuration

Secrets are supplied only at runtime. Common optional variables include:

- `OPENAI_API_KEY` for API-backed visual or speech adapters.
- `QINGSHAN_IMAGE_ANALYSIS_COMMAND` for an exact-SHA visual analysis command.
- `QINGSHAN_OCR_PYTHON` for the OCR Python runtime.
- `BACKLOT_PROJECT_ROOT` for the active production project.
- `BACKLOT_MEDIA_BIN_DIR` when FFmpeg is installed outside the system path.
- `AGENTCUT_NALU_ASSET` only when the legacy Nalu outro template is used.
- `AGENTCUT_SUBTITLE_FONT` for a platform-specific CJK-capable font file. The font and every required glyph remain hard validation gates.

Compatibility variable names remain supported until a versioned migration introduces BacklotOS aliases. `doctor.sh` reports whether values exist but never prints them.

### StoryClaw native model runtime

StoryClaw already supplies the host Agent model. BacklotOS detects StoryClaw
from its runtime environment (or `BACKLOT_RUNTIME_PROFILE=storyclaw`) and marks
`OPENAI_API_KEY` as `NOT_APPLICABLE`; users must not buy or paste a second key
to run the core pipeline there. `BACKLOT_HOST_MODEL` may label the host-managed
model in health output without exposing credentials.

The host Agent's model session and a child CLI process are separate execution
boundaries. Agent-mediated writing, reasoning, and visual inspection use the
StoryClaw model without an API key. Fully unattended CLI image review still
needs an exact-SHA command bridge via `QINGSHAN_IMAGE_ANALYSIS_COMMAND`; doctor
reports that bridge independently and never treats the ambient model session
as proof that the command adapter ran. Standalone servers may optionally use
`OPENAI_API_KEY` for direct API-backed adapters.

The official installer includes RapidOCR, ONNX Runtime, and headless OpenCV in
the isolated BacklotOS environment. Review Agent OCR automatically uses its own
Python interpreter, so `QINGSHAN_OCR_PYTHON` becomes `NOT_APPLICABLE` after a
normal installation. The compatibility variable is retained only for operators
who intentionally supply a separate OCR environment.

When `BACKLOT_STORYCLAW_API_KEY` is supplied through the StoryClaw device secret
store, Review Agent automatically uses the bundled exact-SHA image adapter at
`https://llm.storyclaw.com/v1/chat/completions`. The default model is `gpt-5.5`
and can be changed with `BACKLOT_STORYCLAW_MODEL`; the endpoint may be changed
with `BACKLOT_STORYCLAW_API_BASE`. The key is never accepted in request JSON,
reports, command arguments, or repository files.

## Update and rollback

For Git checkouts, `scripts/update.sh` fetches the requested branch or tag and reinstalls the isolated environment. Set `BACKLOT_VERSION` to an immutable tag for production. To roll back, set it to the previous tag and rerun the script.

After every update, run `scripts/doctor.sh` from the exact checkout used for
installation. The doctor compares both the installed version record and the
installed paid image/video gate bytes with that checkout and fails closed on
drift. The production video gate currently admits only `seedance-2.0-fast`;
neither a project manifest nor a stale provider registry may widen that model
policy. A merged tag is not production-ready until this deployed-code parity
check passes on the production machine.

When the production project is outside the BacklotOS installation, image
manifest prechecks and submissions must name it explicitly:

```bash
submit_giggle_image_manifest.py \
  --project-root /absolute/path/to/production-project \
  --manifest workflow/image_manifest.json \
  --out qa/image_submit_report.json \
  --precheck-only
```

All relative manifests, prompts, references, gate reports, output reports, and
durable transaction paths resolve under that validated directory. Omitting
`--project-root` preserves the installed-layout behavior for compatibility.

Archive installations have no Git remote by design. Update them by downloading the next release archive, verifying the SHA-256 published on its release page, and running that archive's `scripts/install.sh` with the existing `BACKLOT_INSTALL_DIR`. Retain the previous archive until the new `scripts/doctor.sh` run passes.

## Cloud

The Review Agent includes a Docker-based cloud service under `components/review-agent/cloud`. The Factory Runtime can also be installed as a file-native worker. Cloud deployments must mount project media externally; media is never baked into source images or Git releases.

## Test tiers

CI runs portable contract tests on every pull request. The full Review Agent regression corpus additionally needs a production evidence root and can be run with `BACKLOT_PROJECT_ROOT=/path/to/project python -m unittest discover -s components/review-agent/tests -v`. This separation prevents a missing private corpus from being reported as a product failure while preserving the full production suite for release acceptance.
## Ordinary-user launch

After `./scripts/install.sh`, start the local console:

```bash
${BACKLOT_INSTALL_DIR:-$HOME/.local/share/backlotos}/venv/bin/backlotos start
```

The console binds to `127.0.0.1` by default and is not exposed to the network.
Projects are stored under `~/BacklotOS/projects` unless
`BACKLOT_PROJECTS_DIR` is configured. URL intake accepts only public HTTP(S)
destinations and rejects credentials, localhost, and private-network targets.

## Five-agent cloud deployment

```bash
cp deploy/five-agent/.env.example deploy/five-agent/.env
docker compose -f deploy/five-agent/docker-compose.yml up --build -d
```

Only the workbench is published to the host by default. The five Agent ports
remain on the private Compose network. Configure `BACKLOT_AGENT_TOKEN` before
exposing an Agent endpoint outside that network. See
`deploy/five-agent/README.md` for the current capability matrix and the two
versioned command adapters. The Producer adapter is installed by the image;
the Pipeline adapter runs deterministic generic gates but reports
`ADAPTER_REQUIRED` for provider-backed media generation until configured.
