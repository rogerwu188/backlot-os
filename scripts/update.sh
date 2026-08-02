#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target_version="${BACKLOT_VERSION:-main}"

git -C "$repo_root" fetch --tags origin
git -C "$repo_root" diff --quiet && git -C "$repo_root" diff --cached --quiet || {
  echo "Local changes detected; update stopped to protect your work." >&2
  exit 3
}
git -C "$repo_root" checkout "$target_version"
if [[ "$target_version" == "main" ]]; then
  git -C "$repo_root" pull --ff-only origin main
fi
"$repo_root/scripts/install.sh"

