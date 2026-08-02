# Deployment

## Workstation

Run `./scripts/install.sh`. By default, the isolated runtime is installed under `$XDG_DATA_HOME/backlotos` or `~/.local/share/backlotos`. Override it with `BACKLOT_INSTALL_DIR`.

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

## Update and rollback

`scripts/update.sh` fetches the requested branch or tag and reinstalls the isolated environment. Set `BACKLOT_VERSION` to an immutable tag for production. To roll back, set it to the previous tag and rerun the script.

## Cloud

The Review Agent includes a Docker-based cloud service under `components/review-agent/cloud`. The Factory Runtime can also be installed as a file-native worker. Cloud deployments must mount project media externally; media is never baked into source images or Git releases.

## Test tiers

CI runs portable contract tests on every pull request. The full Review Agent regression corpus additionally needs a production evidence root and can be run with `BACKLOT_PROJECT_ROOT=/path/to/project python -m unittest discover -s components/review-agent/tests -v`. This separation prevents a missing private corpus from being reported as a product failure while preserving the full production suite for release acceptance.
