#!/usr/bin/env bash
set -euo pipefail

install_root="${BACKLOT_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/backlotos}"
failed=0

check_command() {
  if command -v "$1" >/dev/null 2>&1; then
    echo "PASS command:$1"
  else
    echo "FAIL command:$1"
    failed=1
  fi
}

check_command git
check_command ffmpeg
check_command ffprobe
check_command node

if [[ -x "$install_root/venv/bin/qingshan-review" ]]; then
  echo "PASS review-agent"
  "$install_root/venv/bin/qingshan-review" health
else
  echo "FAIL review-agent"
  failed=1
fi

if [[ -x "$install_root/venv/bin/agentcut" ]]; then
  echo "PASS agentcut"
  "$install_root/venv/bin/agentcut" health
else
  echo "FAIL agentcut"
  failed=1
fi

if [[ -x "$install_root/venv/bin/claude-story-agent" ]]; then
  echo "PASS story-agent"
  "$install_root/venv/bin/claude-story-agent" health
else
  echo "FAIL story-agent"
  failed=1
fi

for variable_name in OPENAI_API_KEY QINGSHAN_IMAGE_ANALYSIS_COMMAND QINGSHAN_OCR_PYTHON; do
  if [[ -n "${!variable_name:-}" ]]; then
    echo "CONFIGURED $variable_name"
  else
    echo "OPTIONAL_NOT_CONFIGURED $variable_name"
  fi
done

exit "$failed"
