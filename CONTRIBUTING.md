# Contributing

All changes use an `agent/*` or `feature/*` branch and a pull request. Direct production deployment is never part of a source update.

Before opening a pull request:

1. Run `./scripts/verify-repository.sh`.
2. Run the affected component tests.
3. Confirm no production media, evidence, credentials, or runtime state is staged.
4. Record behavior and compatibility changes in `CHANGELOG.md`.

The default update flow is source change → tests → pull request → review → merge → version tag → explicit installation. This gives every machine a reproducible rollback point.

