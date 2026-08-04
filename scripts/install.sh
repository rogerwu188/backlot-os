#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/scripts/lib/source-metadata.sh"
source "$repo_root/scripts/lib/python-runtime.sh"
install_root="${BACKLOT_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/backlotos}"
python_bin="$(backlot_select_python)" || {
  echo "Python 3.10, 3.11, or 3.12 is required (3.13+ is not yet supported by the OCR runtime)." >&2
  exit 2
}
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

backlot_write_source_metadata "$repo_root" "$install_root"

echo "BacklotOS installed at $install_root"
echo "Start the production console with: $install_root/venv/bin/backlotos start"
BACKLOT_INSTALL_DIR="$install_root" "$repo_root/scripts/doctor.sh"
