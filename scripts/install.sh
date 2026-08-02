#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install_root="${BACKLOT_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/backlotos}"
python_bin="${BACKLOT_PYTHON:-}"

if [[ -z "$python_bin" ]]; then
  for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,10))'; then
      python_bin="$candidate"
      break
    fi
  done
fi

[[ -n "$python_bin" ]] || { echo "Python 3.10 or newer is required." >&2; exit 2; }
command -v "$python_bin" >/dev/null || { echo "Python 3.10 or newer is required." >&2; exit 2; }
command -v git >/dev/null || { echo "Git is required." >&2; exit 2; }
command -v ffmpeg >/dev/null || { echo "FFmpeg is required." >&2; exit 2; }
command -v ffprobe >/dev/null || { echo "FFprobe is required." >&2; exit 2; }

mkdir -p "$install_root"
"$python_bin" -m venv "$install_root/venv"
"$install_root/venv/bin/python" -m pip install --upgrade pip
"$install_root/venv/bin/python" -m pip install "$repo_root/components/agentcut" "$repo_root/components/review-agent" "$repo_root/components/story-agent" "$repo_root/components/producer-supervisor-agent" "$repo_root/components/launcher"

share_stage="$(mktemp -d "$install_root/share.next.XXXXXX")"
cp -R "$repo_root/components/factory-runtime" "$share_stage/factory-runtime"
cp -R "$repo_root/components/pipeline-tools" "$share_stage/pipeline-tools"
cp -R "$repo_root/components/agent-factory" "$share_stage/agent-factory"
if [[ -d "$install_root/share" ]]; then
  mv "$install_root/share" "$install_root/share.previous.$(date +%Y%m%d%H%M%S)"
fi
mv "$share_stage" "$install_root/share"

mkdir -p "$install_root/source"
printf '%s\n' "$repo_root" > "$install_root/source/repository-path"
printf '%s\n' "$(tr -d '[:space:]' < "$repo_root/VERSION")" > "$install_root/source/version"

echo "BacklotOS installed at $install_root"
echo "Start the production console with: $install_root/venv/bin/backlotos start"
BACKLOT_INSTALL_DIR="$install_root" "$repo_root/scripts/doctor.sh"
