#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
git -C "$repo_root" config core.hooksPath .githooks
chmod +x "$repo_root/.githooks/post-commit"
echo "Automatic GitHub branch sync enabled for $repo_root"
echo "Set BACKLOT_DISABLE_AUTO_PUSH=1 for a one-off local-only commit."
